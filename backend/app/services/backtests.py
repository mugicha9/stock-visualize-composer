from __future__ import annotations

import sqlite3
from calendar import monthrange
from datetime import date, datetime, timedelta
from typing import Any

from ..database import get_active_prompt_template, get_setting, row_to_dict
from ..models import BacktestPeriodInfoRequest, BacktestRequest
from .company_sources import YahooJapanFinanceSource, update_disclosures_for_company, update_news_for_company
from .features import build_llm_input
from .global_news import update_global_news
from .information_dates import ensure_information_date_columns, infer_information_date, refresh_information_dates
from .llm import provider_from_settings, validate_judgement_output
from .source_events import source_event_counts


ENTRY_ACTIONS = {"BUY", "WATCH_BUY"}
EXIT_ACTIONS = {"SELL", "WATCH_SELL"}


def run_backtest(conn: sqlite3.Connection, request: BacktestRequest) -> dict[str, Any]:
    company = row_to_dict(
        conn.execute(
            "SELECT * FROM companies WHERE security_code = ? AND is_active = 1",
            (request.security_code,),
        ).fetchone()
    )
    if company is None:
        raise ValueError(f"Company not found: {request.security_code}")

    latest_date = _latest_price_date(conn, int(company["id"]))
    if latest_date is None:
        raise ValueError(f"Price data not found: {request.security_code}")

    end_dt = _parse_iso_date(request.end_date, "end_date") if request.end_date else _parse_iso_date(latest_date, "latest_date")
    latest_dt = _parse_iso_date(latest_date, "latest_date")
    if end_dt > latest_dt:
        end_dt = latest_dt
    start_dt = _parse_iso_date(request.start_date, "start_date") if request.start_date else end_dt - timedelta(days=365)
    if start_dt >= end_dt:
        raise ValueError("start_date must be before end_date")

    bars = _price_rows(conn, int(company["id"]), start_dt.isoformat(), end_dt.isoformat())
    if len(bars) < 2:
        raise ValueError("Backtest requires at least two daily price bars in the selected period")

    decision_indices = _decision_indices(bars, request.interval)
    truncated = False
    if len(decision_indices) > request.max_steps:
        decision_indices = decision_indices[: request.max_steps]
        truncated = True

    prompt = get_active_prompt_template(conn)
    provider = provider_from_settings(conn, request.provider, request.model_name)

    realized_value = 1.0
    position: dict[str, Any] | None = None
    decisions: list[dict[str, Any]] = []
    trades: list[dict[str, Any]] = []
    equity_curve: list[dict[str, Any]] = []
    errors: list[dict[str, str]] = []

    for index in decision_indices:
        bar = bars[index]
        next_bar = bars[index + 1]
        decision_date = str(bar["date"])
        close = _number(bar.get("close"))
        mark_value = _mark_to_market(realized_value, position, close)
        equity_curve.append(_equity_point(decision_date, mark_value))

        try:
            llm_input = build_llm_input(conn, request.security_code, as_of=decision_date)
            output = validate_judgement_output(provider.generate(prompt["template_text"], llm_input))
            data_counts = _data_counts(llm_input)
            warnings = list(llm_input.get("data_quality", {}).get("warnings") or [])
        except Exception as exc:  # noqa: BLE001 - keep backtest running and surface failed steps.
            output = _fallback_output(str(exc))
            data_counts = {}
            warnings = ["judgement_generation_failed"]
            errors.append({"date": decision_date, "message": str(exc)})

        execution_price = _execution_price(next_bar)
        execution_date = str(next_bar["date"])
        executed_action: str | None = None
        trade: dict[str, Any] | None = None
        action = output["action"]

        if execution_price is not None and position is None and action in ENTRY_ACTIONS:
            position = {
                "entry_date": execution_date,
                "entry_price": execution_price,
                "entry_signal_date": decision_date,
                "entry_signal": action,
            }
            executed_action = "BUY"
        elif execution_price is not None and position is not None and action in EXIT_ACTIONS:
            trade = _close_trade(position, execution_date, execution_price, decision_date, action, "signal")
            trades.append(trade)
            realized_value *= execution_price / float(position["entry_price"])
            position = None
            executed_action = "SELL"

        decisions.append(
            {
                "date": decision_date,
                "price_close": close,
                "action": action,
                "confidence": output["confidence"],
                "summary": output["summary"],
                "data_as_of": decision_date,
                "data_counts": data_counts,
                "data_warnings": warnings,
                "next_execution_date": execution_date,
                "next_execution_price": execution_price,
                "executed_action": executed_action,
                "position_after": "long" if position else "flat",
                "equity_pct": (mark_value - 1.0) * 100,
                "trade": trade,
            }
        )

    final_bar = bars[-1]
    final_price = _number(final_bar.get("close")) or _execution_price(final_bar)
    if position is not None and final_price is not None:
        trade = _close_trade(position, str(final_bar["date"]), final_price, str(final_bar["date"]), "SELL", "end_of_period")
        trades.append(trade)
        realized_value *= final_price / float(position["entry_price"])
        position = None
    equity_curve.append(_equity_point(str(final_bar["date"]), realized_value))

    benchmark_return_pct = _buy_and_hold_return_pct(bars)
    summary = _summary(realized_value, benchmark_return_pct, trades, equity_curve)

    return {
        "company": {
            "id": company["id"],
            "security_code": company["security_code"],
            "name": company["name"],
            "market": company["market"],
            "sector": company["sector"],
            "industry": company["industry"],
        },
        "config": {
            "start_date": str(bars[0]["date"]),
            "end_date": str(final_bar["date"]),
            "requested_start_date": start_dt.isoformat(),
            "requested_end_date": end_dt.isoformat(),
            "interval": request.interval,
            "provider": provider.name,
            "model_name": provider.model_name,
            "execution_policy": "中長期判断のBUY/WATCH_BUYで次営業日始値に1単元買い、SELL/WATCH_SELLで次営業日始値に全て売却",
            "max_steps": request.max_steps,
            "truncated": truncated,
        },
        "summary": summary,
        "decisions": decisions,
        "trades": trades,
        "equity_curve": equity_curve,
        "errors": errors,
        "leakage_guard": {
            "as_of_filter": "判断入力は price_bars / technical_indicators / source_events / company_financials を判断日以下で取得します。",
            "execution_timing": "判断は判断日終値までの情報で作り、売買は次の取引日の始値で約定させます。",
            "storage": "バックテスト中のContext Packetはメモリ上で生成し、売買判断履歴はバックテスト結果に保持します。",
        },
    }


def fetch_backtest_period_info(conn: sqlite3.Connection, request: BacktestPeriodInfoRequest) -> dict[str, Any]:
    company = row_to_dict(
        conn.execute(
            "SELECT * FROM companies WHERE security_code = ? AND is_active = 1",
            (request.security_code,),
        ).fetchone()
    )
    if company is None:
        raise ValueError(f"Company not found: {request.security_code}")

    latest_date = _latest_price_date(conn, int(company["id"]))
    if latest_date is None:
        raise ValueError(f"Price data not found: {request.security_code}")
    end_dt = _parse_iso_date(request.end_date, "end_date") if request.end_date else _parse_iso_date(latest_date, "latest_date")
    latest_dt = _parse_iso_date(latest_date, "latest_date")
    if end_dt > latest_dt:
        end_dt = latest_dt
    start_dt = _parse_iso_date(request.start_date, "start_date") if request.start_date else end_dt - timedelta(days=365)
    if start_dt >= end_dt:
        raise ValueError("start_date must be before end_date")

    ensure_information_date_columns(conn)
    before = _period_coverage(conn, int(company["id"]), start_dt.isoformat(), end_dt.isoformat())
    fetched: dict[str, Any] = {}
    source_notes: list[str] = []

    if request.persist:
        if request.include_news:
            fetched["company_news"] = len(update_news_for_company(conn, request.security_code, limit=request.news_limit))
        if request.include_disclosures:
            fetched["disclosures"] = len(update_disclosures_for_company(conn, request.security_code, limit=request.disclosure_limit))
        if request.include_external_factors:
            fetched["global_news"] = update_global_news(
                conn,
                limit_per_source=int(get_setting(conn, "global_news_fetch_limit_per_source", "40") or "40"),
            )["count"]
        refresh_information_dates(conn)
        after = _period_coverage(conn, int(company["id"]), start_dt.isoformat(), end_dt.isoformat())
    else:
        preview = _preview_period_info(request, start_dt.isoformat(), end_dt.isoformat())
        fetched = preview["fetched"]
        after = before
        source_notes.extend(preview["source_notes"])
        source_notes.append("persist=false のため、取得結果はDBへ保存されずバックテスト入力には使われません。")

    return {
        "company": {
            "id": company["id"],
            "security_code": company["security_code"],
            "name": company["name"],
        },
        "period": {
            "start_date": start_dt.isoformat(),
            "end_date": end_dt.isoformat(),
        },
        "persisted": request.persist,
        "requested": {
            "include_news": request.include_news,
            "include_disclosures": request.include_disclosures,
            "include_external_factors": request.include_external_factors,
        },
        "fetched": fetched,
        "coverage_before": before,
        "coverage_after": after,
        "source_notes": source_notes
        or [
            "既存スクレイパーは取得元ページに掲載されている範囲を取得します。古い期間の履歴が取得元にない場合は0件のままです。"
        ],
    }


def _latest_price_date(conn: sqlite3.Connection, company_id: int) -> str | None:
    row = conn.execute(
        """
        SELECT MAX(date) AS latest_date
        FROM price_bars
        WHERE company_id = ? AND timeframe = '1d'
        """,
        (company_id,),
    ).fetchone()
    return row["latest_date"] if row else None


def _price_rows(conn: sqlite3.Connection, company_id: int, start_date: str, end_date: str) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT date, open, high, low, close, volume, adjusted_close, source
        FROM price_bars
        WHERE company_id = ?
          AND timeframe = '1d'
          AND date >= ?
          AND date <= ?
        ORDER BY date ASC
        """,
        (company_id, start_date, end_date),
    ).fetchall()
    return [dict(row) for row in rows]


def _period_coverage(conn: sqlite3.Connection, company_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    event_counts = source_event_counts(conn, company_id=company_id, start_date=start_date, end_date=end_date)
    return {
        "source_events": event_counts,
        "company_news": {
            "available": event_counts["company_news"],
            "earliest_date": event_counts["earliest_date"],
            "latest_date": event_counts["latest_date"],
            "missing_information_date": event_counts["missing_information_date"],
        },
        "disclosures": {
            "available": event_counts["disclosures"],
            "earliest_date": event_counts["earliest_date"],
            "latest_date": event_counts["latest_date"],
            "missing_information_date": event_counts["missing_information_date"],
        },
        "global_news": {
            "available": event_counts["global_news"],
            "earliest_date": event_counts["earliest_date"],
            "latest_date": event_counts["latest_date"],
            "missing_information_date": event_counts["missing_information_date"],
        },
        "company_financials": _financial_period_count(conn, company_id, start_date, end_date),
    }


def _table_period_count(
    conn: sqlite3.Connection,
    table: str,
    company_id: int,
    start_date: str,
    end_date: str,
) -> dict[str, Any]:
    date_expr = "COALESCE(information_date, substr(published_at, 1, 10))"
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS available,
            MIN({date_expr}) AS earliest_date,
            MAX({date_expr}) AS latest_date
        FROM {table}
        WHERE company_id = ?
          AND {date_expr} IS NOT NULL
          AND {date_expr} >= ?
          AND {date_expr} <= ?
        """,
        (company_id, start_date, end_date),
    ).fetchone()
    missing = conn.execute(
        f"""
        SELECT COUNT(*) AS missing
        FROM {table}
        WHERE company_id = ?
          AND ({date_expr} IS NULL OR {date_expr} = '')
        """,
        (company_id,),
    ).fetchone()
    return {
        "available": int(row["available"] if row else 0),
        "earliest_date": row["earliest_date"] if row else None,
        "latest_date": row["latest_date"] if row else None,
        "missing_information_date": int(missing["missing"] if missing else 0),
    }


def _financial_period_count(conn: sqlite3.Connection, company_id: int, start_date: str, end_date: str) -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT COUNT(*) AS available, MIN(as_of) AS earliest_date, MAX(as_of) AS latest_date
        FROM company_financials
        WHERE company_id = ?
          AND as_of >= ?
          AND as_of <= ?
        """,
        (company_id, start_date, end_date),
    ).fetchone()
    return {
        "available": int(row["available"] if row else 0),
        "earliest_date": row["earliest_date"] if row else None,
        "latest_date": row["latest_date"] if row else None,
        "missing_information_date": 0,
    }


def _global_period_count(conn: sqlite3.Connection, start_date: str, end_date: str) -> dict[str, Any]:
    date_expr = "COALESCE(information_date, substr(published_at, 1, 10))"
    row = conn.execute(
        f"""
        SELECT COUNT(*) AS available, MIN({date_expr}) AS earliest_date, MAX({date_expr}) AS latest_date
        FROM global_news
        WHERE {date_expr} IS NOT NULL
          AND {date_expr} >= ?
          AND {date_expr} <= ?
        """,
        (start_date, end_date),
    ).fetchone()
    missing = conn.execute(
        f"""
        SELECT COUNT(*) AS missing
        FROM global_news
        WHERE {date_expr} IS NULL OR {date_expr} = ''
        """
    ).fetchone()
    return {
        "available": int(row["available"] if row else 0),
        "earliest_date": row["earliest_date"] if row else None,
        "latest_date": row["latest_date"] if row else None,
        "missing_information_date": int(missing["missing"] if missing else 0),
    }


def _preview_period_info(request: BacktestPeriodInfoRequest, start_date: str, end_date: str) -> dict[str, Any]:
    source = YahooJapanFinanceSource()
    fetched: dict[str, Any] = {}
    source_notes: list[str] = []
    if request.include_news:
        items = source.fetch_news(request.security_code, limit=request.news_limit)
        fetched["company_news"] = _preview_count(items, start_date, end_date)
    if request.include_disclosures:
        items = source.fetch_disclosures(request.security_code, limit=request.disclosure_limit)
        fetched["disclosures"] = _preview_count(items, start_date, end_date)
    if request.include_external_factors:
        fetched["global_news"] = {"fetched": 0, "available_in_period": 0}
        source_notes.append("全体ニュースは共有DBと重複排除を使うため、保存なしプレビューでは取得しません。")
    return {"fetched": fetched, "source_notes": source_notes}


def _preview_count(items: list[dict[str, Any]], start_date: str, end_date: str) -> dict[str, int]:
    available = 0
    missing = 0
    for item in items:
        information_date = infer_information_date(
            title=item.get("title"),
            published_at=item.get("published_at"),
            url=item.get("url"),
        )
        if information_date is None:
            missing += 1
            continue
        if start_date <= information_date <= end_date:
            available += 1
    return {"fetched": len(items), "available_in_period": available, "missing_information_date": missing}


def _decision_indices(bars: list[dict[str, Any]], interval: str) -> list[int]:
    if interval == "1d":
        return list(range(0, len(bars) - 1))

    indices: list[int] = []
    next_decision_date: date | None = None
    for index, bar in enumerate(bars[:-1]):
        current = _parse_iso_date(str(bar["date"]), "bar.date")
        if next_decision_date is None or current >= next_decision_date:
            indices.append(index)
            next_decision_date = _next_decision_date(current, interval)
    return indices


def _next_decision_date(current: date, interval: str) -> date:
    if interval == "1w":
        return current + timedelta(days=7)
    if interval == "2w":
        return current + timedelta(days=14)
    if interval == "1mo":
        return _add_month(current)
    raise ValueError(f"Unsupported backtest interval: {interval}")


def _add_month(current: date) -> date:
    year = current.year + (1 if current.month == 12 else 0)
    month = 1 if current.month == 12 else current.month + 1
    day = min(current.day, monthrange(year, month)[1])
    return date(year, month, day)


def _parse_iso_date(value: str | None, field_name: str) -> date:
    if not value:
        raise ValueError(f"{field_name} is required")
    try:
        return datetime.fromisoformat(value[:10]).date()
    except ValueError as exc:
        raise ValueError(f"{field_name} must be YYYY-MM-DD") from exc


def _number(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _execution_price(bar: dict[str, Any]) -> float | None:
    return _number(bar.get("open")) or _number(bar.get("close"))


def _mark_to_market(realized_value: float, position: dict[str, Any] | None, close: float | None) -> float:
    if position is None or close is None:
        return realized_value
    return realized_value * close / float(position["entry_price"])


def _equity_point(point_date: str, value: float) -> dict[str, Any]:
    return {
        "date": point_date,
        "normalized_value": value,
        "return_pct": (value - 1.0) * 100,
    }


def _close_trade(
    position: dict[str, Any],
    exit_date: str,
    exit_price: float,
    exit_signal_date: str,
    exit_signal: str,
    exit_reason: str,
) -> dict[str, Any]:
    entry_price = float(position["entry_price"])
    return_pct = (exit_price / entry_price - 1.0) * 100
    return {
        "entry_date": position["entry_date"],
        "entry_price": entry_price,
        "entry_signal_date": position["entry_signal_date"],
        "entry_signal": position["entry_signal"],
        "exit_date": exit_date,
        "exit_price": exit_price,
        "exit_signal_date": exit_signal_date,
        "exit_signal": exit_signal,
        "exit_reason": exit_reason,
        "return_pct": return_pct,
    }


def _fallback_output(message: str) -> dict[str, Any]:
    return {
        "judgement_type": "mid_long_term",
        "action": "INSUFFICIENT_DATA",
        "confidence": 0.0,
        "time_horizon": "3_months_to_1_year",
        "summary": "この時点のAI判断生成に失敗したため、売買は見送ります。",
        "positive_factors": ["保存済み価格データは確認しました。"],
        "negative_factors": [f"AI判断生成エラー: {message}"],
        "entry_conditions": ["判断生成が正常に完了するまで新規買いを見送ります。"],
        "exit_conditions": ["判断生成が正常に完了するまで既存方針を維持します。"],
        "risk_notes": ["このステップはバックテスト結果の誤差要因になります。"],
        "used_signal_ids": [],
    }


def _data_counts(llm_input: dict[str, Any]) -> dict[str, int]:
    event_context = llm_input.get("event_context") or {}
    return {
        "recent_disclosures": len(event_context.get("recent_disclosures") or []),
        "selected_company_news": len(event_context.get("selected_company_news") or []),
        "selected_global_news": len(event_context.get("selected_global_news") or []),
        "has_financial_snapshot": 1 if event_context.get("latest_financial_snapshot") else 0,
    }


def _buy_and_hold_return_pct(bars: list[dict[str, Any]]) -> float | None:
    if len(bars) < 2:
        return None
    entry_price = _execution_price(bars[1]) or _number(bars[0].get("close"))
    exit_price = _number(bars[-1].get("close")) or _execution_price(bars[-1])
    if entry_price is None or exit_price is None:
        return None
    return (exit_price / entry_price - 1.0) * 100


def _summary(
    realized_value: float,
    benchmark_return_pct: float | None,
    trades: list[dict[str, Any]],
    equity_curve: list[dict[str, Any]],
) -> dict[str, Any]:
    returns = [float(trade["return_pct"]) for trade in trades]
    wins = [value for value in returns if value > 0]
    return {
        "total_return_pct": (realized_value - 1.0) * 100,
        "buy_and_hold_return_pct": benchmark_return_pct,
        "excess_return_pct": ((realized_value - 1.0) * 100 - benchmark_return_pct) if benchmark_return_pct is not None else None,
        "trade_count": len(trades),
        "win_rate_pct": (len(wins) / len(returns) * 100) if returns else None,
        "average_trade_return_pct": (sum(returns) / len(returns)) if returns else None,
        "max_drawdown_pct": _max_drawdown_pct(equity_curve),
    }


def _max_drawdown_pct(equity_curve: list[dict[str, Any]]) -> float:
    peak = 1.0
    max_drawdown = 0.0
    for point in equity_curve:
        value = float(point.get("normalized_value") or 1.0)
        peak = max(peak, value)
        if peak > 0:
            max_drawdown = min(max_drawdown, value / peak - 1.0)
    return max_drawdown * 100
