from __future__ import annotations

import json
import sqlite3
from datetime import date, datetime
from typing import Any

from ..database import get_setting, row_to_dict
from .global_news import list_global_news
from .news_relevance import prepare_relevant_news


def _parse_json(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_json_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [str(item).strip() for item in parsed if str(item).strip()]


def _latest_price(
    conn: sqlite3.Connection,
    company_id: int,
    timeframe: str = "1d",
    as_of: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [company_id, timeframe]
    date_filter = ""
    if as_of:
        date_filter = "AND date <= ?"
        params.append(as_of)
    return row_to_dict(
        conn.execute(
            f"""
            SELECT *
            FROM price_bars
            WHERE company_id = ? AND timeframe = ?
              {date_filter}
            ORDER BY date DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    )


def _latest_indicator(
    conn: sqlite3.Connection,
    company_id: int,
    timeframe: str = "1d",
    as_of: str | None = None,
) -> dict[str, Any] | None:
    params: list[Any] = [company_id, timeframe]
    date_filter = ""
    if as_of:
        date_filter = "AND date <= ?"
        params.append(as_of)
    return row_to_dict(
        conn.execute(
            f"""
            SELECT *
            FROM technical_indicators
            WHERE company_id = ? AND timeframe = ?
              {date_filter}
            ORDER BY date DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    )


def _recent_disclosures(
    conn: sqlite3.Connection,
    company_id: int,
    limit: int = 8,
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = [company_id]
    date_expr = "COALESCE(information_date, substr(published_at, 1, 10))"
    date_filter = ""
    if as_of:
        date_filter = f"AND {date_expr} IS NOT NULL AND {date_expr} <= ?"
        params.append(as_of)
    params.append(limit)
    return [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT id, title, document_type, published_at, {date_expr} AS information_date,
                   source, url, summary, importance_score
            FROM disclosures
            WHERE company_id = ?
              {date_filter}
            ORDER BY {date_expr} DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    ]


def _latest_financials(conn: sqlite3.Connection, company_id: int, as_of: str | None = None) -> dict[str, Any] | None:
    params: list[Any] = [company_id]
    date_filter = ""
    if as_of:
        date_filter = "AND as_of <= ?"
        params.append(as_of)
    row = row_to_dict(
        conn.execute(
            f"""
            SELECT id, source, as_of, fiscal_period, next_earnings_date, summary, metrics_json, url
            FROM company_financials
            WHERE company_id = ?
              {date_filter}
            ORDER BY as_of DESC, updated_at DESC
            LIMIT 1
            """,
            params,
        ).fetchone()
    )
    if row and row.get("metrics_json"):
        row["metrics"] = _parse_json(row["metrics_json"])
        row.pop("metrics_json", None)
    return row


def _recent_news(
    conn: sqlite3.Connection,
    company_id: int,
    limit: int = 16,
    as_of: str | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = [company_id]
    date_expr = "COALESCE(information_date, substr(published_at, 1, 10))"
    date_filter = ""
    if as_of:
        date_filter = f"AND {date_expr} IS NOT NULL AND {date_expr} <= ?"
        params.append(as_of)
    params.append(limit)
    return [
        dict(row)
        for row in conn.execute(
            f"""
            SELECT id, title, published_at, {date_expr} AS information_date,
                   source, provider, url, content_text, summary, relevance_score, selection_reason, keyword_hits
            FROM news_articles
            WHERE company_id = ?
              {date_filter}
            ORDER BY {date_expr} DESC, id DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    ]


def _compact_text(value: str | None, limit: int = 220) -> str | None:
    if not value:
        return None
    normalized = " ".join(value.split())
    if len(normalized) <= limit:
        return normalized
    return normalized[: limit - 3] + "..."


def _company_business_profile(
    conn: sqlite3.Connection,
    company: dict[str, Any],
    financials: dict[str, Any] | None,
) -> dict[str, Any]:
    profile_row = row_to_dict(
        conn.execute(
            """
            SELECT company_terms_json, business_terms_json, material_terms_json, exclude_terms_json,
                   generated_by, prompt_version, updated_at
            FROM company_news_profiles
            WHERE company_id = ?
            """,
            (company["id"],),
        ).fetchone()
    )
    company_terms = _parse_json_list(profile_row.get("company_terms_json") if profile_row else None)
    business_terms = _parse_json_list(profile_row.get("business_terms_json") if profile_row else None)
    material_terms = _parse_json_list(profile_row.get("material_terms_json") if profile_row else None)
    exclude_terms = _parse_json_list(profile_row.get("exclude_terms_json") if profile_row else None)

    company_terms = _unique_text([*company_terms, company.get("name"), company.get("security_code")])[:12]
    business_terms = _unique_text([*business_terms, company.get("sector"), company.get("industry")])[:16]
    material_terms = _unique_text(material_terms)[:24]
    exclude_terms = _unique_text(exclude_terms)[:20]
    financial_summary = _compact_text(financials.get("summary") if financials else None, 360)
    return {
        "company_terms": company_terms,
        "business_terms": business_terms,
        "material_terms": material_terms,
        "exclude_terms": exclude_terms,
        "sector": company.get("sector"),
        "industry": company.get("industry"),
        "financial_summary": financial_summary,
        "profile_source": profile_row.get("generated_by") if profile_row else "company_master",
        "profile_version": profile_row.get("prompt_version") if profile_row else None,
        "updated_at": profile_row.get("updated_at") if profile_row else None,
        "interpretation_rule": (
            "ニュースや外部要因は、business_terms、sector、industry、financial_summaryに照らして、"
            "この企業の売上、利益率、需要、原材料、規制、資本政策へどう効くかを判断します。"
        ),
    }


def _unique_text(values: list[Any]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        result.append(text)
    return result


def _event_date(item: dict[str, Any]) -> str | None:
    value = item.get("information_date") or item.get("published_at") or item.get("created_at")
    return str(value) if value else None


def _news_digest(
    news: list[dict[str, Any]],
    disclosures: list[dict[str, Any]],
    global_news: list[dict[str, Any]],
    as_of: str | None,
) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    for item in disclosures:
        event_date = _event_date(item)
        items.append(
            {
                "type": "disclosure",
                "date": event_date,
                "age_days": _days_old(event_date, as_of),
                "source": item.get("source"),
                "category": item.get("document_type"),
                "title": item.get("title"),
                "summary": _compact_text(item.get("summary")),
                "importance_score": item.get("importance_score"),
            }
        )
    for item in news:
        event_date = _event_date(item)
        items.append(
            {
                "type": "company_news",
                "date": event_date,
                "age_days": _days_old(event_date, as_of),
                "source": item.get("source"),
                "provider": item.get("provider"),
                "title": item.get("title"),
                "summary": _compact_text(item.get("summary")),
                "relevance_score": item.get("relevance_score"),
                "selection_reason": item.get("selection_reason"),
            }
        )
    for item in global_news:
        event_date = _event_date(item)
        items.append(
            {
                "type": "global_news",
                "date": event_date,
                "age_days": _days_old(event_date, as_of),
                "source": item.get("source"),
                "provider": item.get("provider"),
                "category": item.get("category"),
                "title": item.get("title"),
                "summary": _compact_text(item.get("summary")),
                "relevance_score": item.get("relevance_score"),
                "selection_reason": item.get("selection_reason"),
            }
        )
    items.sort(key=lambda row: row.get("date") or "", reverse=True)
    return {
        "as_of": as_of,
        "counts": {
            "company_news": len(news),
            "disclosures": len(disclosures),
            "global_news": len(global_news),
        },
        "latest_items": items[:24],
    }


def _is_fundamental_disclosure(item: dict[str, Any]) -> bool:
    text = " ".join(
        str(value or "")
        for value in (
            item.get("title"),
            item.get("document_type"),
            item.get("summary"),
        )
    )
    keywords = [
        "決算",
        "業績",
        "配当",
        "予想",
        "修正",
        "月次",
        "短信",
        "説明資料",
        "有価証券報告",
        "四半期報告",
        "自己株式",
    ]
    return any(keyword in text for keyword in keywords)


def _metric_value(metric: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(metric, dict):
        return None
    return {
        "name": metric.get("name"),
        "value": metric.get("value"),
        "suffix": metric.get("suffix"),
        "update_date": metric.get("update_date") or metric.get("update_date_meta"),
    }


def _fundamental_digest(
    financials: dict[str, Any] | None,
    disclosures: list[dict[str, Any]],
    as_of: str | None,
) -> dict[str, Any]:
    metrics = financials.get("metrics") if financials else {}
    selected_metric_keys = [
        "per",
        "pbr",
        "roe",
        "equity_ratio",
        "dividend_yield",
        "eps",
        "bps",
        "market_cap",
    ]
    financial_disclosures = [item for item in disclosures if _is_fundamental_disclosure(item)]
    opportunity = _fundamental_opportunity(financials, disclosures)
    return {
        "as_of": as_of,
        "opportunity": opportunity,
        "snapshot": (
            {
                "source": financials.get("source"),
                "as_of": financials.get("as_of"),
                "fiscal_period": financials.get("fiscal_period"),
                "next_earnings_date": financials.get("next_earnings_date"),
                "days_to_earnings": _days_until(financials.get("next_earnings_date"), as_of),
                "summary": _compact_text(financials.get("summary"), 360),
                "metrics": {
                    key: value
                    for key in selected_metric_keys
                    if (value := _metric_value((metrics or {}).get(key))) is not None
                },
                "opportunity": opportunity,
            }
            if financials
            else None
        ),
        "financial_disclosures": [
            {
                "date": _event_date(item),
                "age_days": _days_old(_event_date(item), as_of),
                "title": item.get("title"),
                "document_type": item.get("document_type"),
                "source": item.get("source"),
                "summary": _compact_text(item.get("summary"), 260),
                "importance_score": item.get("importance_score"),
            }
            for item in financial_disclosures[:8]
        ],
    }


def _fundamental_opportunity(financials: dict[str, Any] | None, disclosures: list[dict[str, Any]]) -> dict[str, Any]:
    per = _metric_number(financials, "per")
    pbr = _metric_number(financials, "pbr")
    roe = _metric_number(financials, "roe")
    equity_ratio = _metric_number(financials, "equity_ratio")
    dividend_yield = _metric_number(financials, "dividend_yield")

    score = 0
    risk_score = 0
    signals: list[str] = []
    risks: list[str] = []

    if per is not None:
        if per <= 10:
            score += 2
            signals.append("PERが低く、収益対比の割安さが強い可能性があります。")
        elif per <= 15:
            score += 1
            signals.append("PERは過度な割高感を示していません。")
        elif per >= 30:
            risk_score += 1
            risks.append("PERが高く、利益対比では割高感があります。")

    if pbr is not None:
        if pbr <= 1:
            score += 2
            signals.append("PBRが1倍以下で、純資産対比の価値乖離候補です。")
        elif pbr <= 1.5:
            score += 1
            signals.append("PBRは純資産対比で極端な割高感を示していません。")
        elif pbr >= 3:
            risk_score += 1
            risks.append("PBRが高く、純資産対比では割高感があります。")

    if roe is not None:
        if roe >= 12:
            score += 2
            signals.append("ROEが高く、資本効率は価値評価の支援材料です。")
        elif roe >= 8:
            score += 1
            signals.append("ROEは一定の収益性を示しています。")
        elif roe < 5:
            risk_score += 1
            risks.append("ROEが低く、収益性面の価値支援は弱いです。")

    if equity_ratio is not None:
        if equity_ratio >= 45:
            score += 1
            signals.append("自己資本比率が高く、財務安全性が下値耐性になり得ます。")
        elif equity_ratio < 20:
            risk_score += 1
            risks.append("自己資本比率が低く、下落局面で財務リスクが意識されます。")

    if dividend_yield is not None:
        if dividend_yield >= 4:
            score += 2
            signals.append("配当利回りが高く、株主還元面の支援が強い可能性があります。")
        elif dividend_yield >= 3:
            score += 1
            signals.append("配当利回りは株主還元面の支援材料です。")

    disclosure_text = " ".join(str(item.get("title") or "") + " " + str(item.get("summary") or "") for item in disclosures[:8])
    if any(keyword in disclosure_text for keyword in ["下方修正", "減益", "赤字", "減配", "無配", "特別損失"]):
        risk_score += 2
        risks.append("直近開示に業績悪化または株主還元悪化を示す語句があります。")
    if any(keyword in disclosure_text for keyword in ["上方修正", "増配", "自己株式取得", "自社株買い"]):
        score += 1
        signals.append("直近開示に業績・還元面の好材料候補があります。")

    if score >= 6 and risk_score <= 1:
        level = "strong_value_dislocation"
        bias = "technical_weakness_can_be_opportunity"
    elif score >= 4 and risk_score <= 2:
        level = "moderate_value_support"
        bias = "avoid_forced_sell"
    elif risk_score >= 3:
        level = "fundamental_risk"
        bias = "technical_weakness_is_more_serious"
    elif score == 0 and risk_score == 0:
        level = "unknown"
        bias = "insufficient_fundamental_basis"
    else:
        level = "limited_value_support"
        bias = "technical_confirmation_needed"

    return {
        "level": level,
        "score": score,
        "risk_score": risk_score,
        "decision_bias": bias,
        "signals": signals[:6],
        "risks": risks[:6],
    }


def _days_old(iso_date: str | None, base_date: str | None = None) -> int | None:
    if not iso_date:
        return None
    try:
        parsed = datetime.fromisoformat(iso_date[:10]).date()
        base = datetime.fromisoformat(base_date[:10]).date() if base_date else date.today()
    except ValueError:
        return None
    return (base - parsed).days


def _days_until(iso_date: str | None, base_date: str | None = None) -> int | None:
    if not iso_date:
        return None
    try:
        parsed = datetime.fromisoformat(iso_date[:10]).date()
        base = datetime.fromisoformat(base_date[:10]).date() if base_date else date.today()
    except ValueError:
        return None
    return (parsed - base).days


def _metric_number(financials: dict[str, Any] | None, key: str) -> float | None:
    if not financials:
        return None
    metric = (financials.get("metrics") or {}).get(key)
    if not isinstance(metric, dict):
        return None
    value = metric.get("value")
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except ValueError:
        return None


def _fundamental_context(financials: dict[str, Any] | None, as_of: str | None = None) -> dict[str, Any]:
    per = _metric_number(financials, "per")
    pbr = _metric_number(financials, "pbr")
    roe = _metric_number(financials, "roe")
    equity_ratio = _metric_number(financials, "equity_ratio")
    dividend_yield = _metric_number(financials, "dividend_yield")
    next_earnings_date = financials.get("next_earnings_date") if financials else None
    return {
        "valuation": {
            "per": per,
            "pbr": pbr,
            "direction": _valuation_direction(per, pbr),
        },
        "profitability": {
            "roe": roe,
            "direction": "strong" if roe is not None and roe >= 10 else "weak" if roe is not None and roe < 5 else "neutral",
        },
        "financial_safety": {
            "equity_ratio": equity_ratio,
            "direction": (
                "strong"
                if equity_ratio is not None and equity_ratio >= 40
                else "weak"
                if equity_ratio is not None and equity_ratio < 20
                else "neutral"
            ),
        },
        "shareholder_return": {
            "dividend_yield": dividend_yield,
            "direction": (
                "supportive"
                if dividend_yield is not None and dividend_yield >= 3
                else "limited"
                if dividend_yield is not None and dividend_yield < 1
                else "neutral"
            ),
        },
        "earnings_event": {
            "next_earnings_date": next_earnings_date,
            "days_to_earnings": _days_until(next_earnings_date, as_of),
        },
        "summary": financials.get("summary") if financials else None,
    }


def _valuation_direction(per: float | None, pbr: float | None) -> str:
    if per is None and pbr is None:
        return "unknown"
    if (per is not None and per <= 12) and (pbr is None or pbr <= 1.5):
        return "undemanding"
    if (per is not None and per >= 30) or (pbr is not None and pbr >= 3):
        return "expensive"
    return "neutral"


def build_llm_input(
    conn: sqlite3.Connection,
    security_code: str,
    timeframe: str = "1d",
    as_of: str | None = None,
    use_llm_news_selection: bool | None = None,
) -> dict[str, Any]:
    company = row_to_dict(
        conn.execute(
            "SELECT * FROM companies WHERE security_code = ? AND is_active = 1",
            (security_code,),
        ).fetchone()
    )
    if company is None:
        raise ValueError(f"Company not found: {security_code}")

    latest_price = _latest_price(conn, int(company["id"]), timeframe, as_of)
    latest_indicator = _latest_indicator(conn, int(company["id"]), timeframe, as_of)
    features = _parse_json(latest_indicator["features_json"] if latest_indicator else None)
    effective_as_of = as_of or (latest_price["date"] if latest_price else None)
    disclosures = _recent_disclosures(conn, int(company["id"]), as_of=effective_as_of)
    financials = _latest_financials(conn, int(company["id"]), as_of=effective_as_of)
    company_profile = _company_business_profile(conn, company, financials)
    company_for_llm = {**company, "business_profile": company_profile}
    news = _recent_news(conn, int(company["id"]), as_of=effective_as_of)
    shared_news = list_global_news(conn, limit=40, as_of=effective_as_of)
    live_run = as_of is None
    use_llm_selection = (
        use_llm_news_selection
        if use_llm_news_selection is not None
        else (get_setting(conn, "default_llm_provider", "mock") != "mock")
    )
    selected_news = prepare_relevant_news(
        conn,
        company=company_for_llm,
        company_news=news,
        global_news=shared_news,
        max_company=int(get_setting(conn, "llm_news_selection_max_company", "4") or "4"),
        max_global=int(get_setting(conn, "llm_news_selection_max_global", "5") or "5"),
        allow_fetch=live_run,
        use_llm_ranking=live_run and bool(use_llm_selection),
    )
    selected_company_news = selected_news["company_news"]
    selected_global_news = selected_news["global_news"]

    data_warnings: list[str] = []
    if latest_price is None:
        data_warnings.append("price_data_missing")
    if latest_indicator is None or not features:
        data_warnings.append("technical_indicators_missing")
    latest_price_age_days = _days_old(latest_price["date"] if latest_price else None, effective_as_of)
    if latest_price_age_days is not None and latest_price_age_days >= 5:
        data_warnings.append("price_data_stale")
    required_features = ["ma_5", "ma_25", "ma_75", "volume_ratio_5d", "volatility_20d"]
    if any(features.get(key) is None for key in required_features):
        data_warnings.append("insufficient_technical_history")
    if financials is None:
        data_warnings.append("financial_snapshot_missing")
    elif not (financials.get("metrics") or {}):
        data_warnings.append("financial_metrics_missing")

    return {
        "company": {
            "security_code": company["security_code"],
            "name": company["name"],
            "market": company["market"],
            "sector": company["sector"],
            "industry": company["industry"],
            "business_profile": company_profile,
        },
        "as_of": latest_price["date"] if latest_price else (effective_as_of or date.today().isoformat()),
        "price_features": features,
        "event_context": {
            "has_recent_disclosure": bool(disclosures),
            "has_recent_news": bool(news),
            "has_global_news": bool(shared_news),
            "recent_disclosure_summaries": [
                item.get("summary") or item.get("title") for item in disclosures if item.get("summary") or item.get("title")
            ],
            "fundamental_digest": _fundamental_digest(financials, disclosures, effective_as_of),
            "company_business_profile": company_profile,
            "news_digest": _news_digest(selected_company_news, disclosures, selected_global_news, effective_as_of),
            "recent_disclosures": [
                {
                    "title": item.get("title"),
                    "document_type": item.get("document_type"),
                    "published_at": item.get("published_at"),
                    "information_date": item.get("information_date"),
                    "source": item.get("source"),
                    "importance_score": item.get("importance_score"),
                }
                for item in disclosures
            ],
            "recent_news_candidates": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "published_at": item.get("published_at"),
                    "information_date": item.get("information_date"),
                    "provider": item.get("provider"),
                    "source": item.get("source"),
                }
                for item in news
            ],
            "selected_company_news": [
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "published_at": item.get("published_at"),
                    "information_date": item.get("information_date"),
                    "provider": item.get("provider"),
                    "source": item.get("source"),
                    "url": item.get("url"),
                    "summary": item.get("summary"),
                    "relevance_score": item.get("relevance_score"),
                    "selection_reason": item.get("selection_reason"),
                }
                for item in selected_company_news
            ],
            "latest_financial_snapshot": financials,
            "fundamental_context": _fundamental_context(financials, effective_as_of),
            "global_news_candidates": [
                {
                    "id": item.get("id"),
                    "category": item.get("category"),
                    "title": item.get("title"),
                    "published_at": item.get("published_at"),
                    "information_date": item.get("information_date"),
                    "provider": item.get("provider"),
                    "source": item.get("source"),
                }
                for item in shared_news[:20]
            ],
            "selected_global_news": [
                {
                    "id": item.get("id"),
                    "category": item.get("category"),
                    "title": item.get("title"),
                    "published_at": item.get("published_at"),
                    "information_date": item.get("information_date"),
                    "provider": item.get("provider"),
                    "source": item.get("source"),
                    "url": item.get("url"),
                    "summary": item.get("summary"),
                    "relevance_score": item.get("relevance_score"),
                    "selection_reason": item.get("selection_reason"),
                }
                for item in selected_global_news
            ],
            "days_to_earnings": _days_until(financials.get("next_earnings_date"), effective_as_of) if financials else None,
        },
        "market_context": {
            "macro_and_policy_factors": [
                {
                    "category": item.get("category"),
                    "title": item.get("title"),
                    "provider": item.get("provider"),
                    "published_at": item.get("published_at"),
                    "information_date": item.get("information_date"),
                    "relevance_score": item.get("relevance_score"),
                    "selection_reason": item.get("selection_reason"),
                }
                for item in selected_global_news[:5]
            ],
            "nikkei_trend": "unknown",
            "topix_trend": "unknown",
            "sector_trend": "unknown",
        },
        "data_quality": {
            "latest_price_date": latest_price["date"] if latest_price else None,
            "latest_price_age_days": latest_price_age_days,
            "warnings": data_warnings,
        },
    }
