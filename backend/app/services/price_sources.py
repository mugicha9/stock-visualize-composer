from __future__ import annotations

import json
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from typing import Any

from ..database import get_setting, row_to_dict, utc_now, write_update_log
from .indicators import calculate_for_company


class PriceSourceError(RuntimeError):
    pass


class YahooFinanceChartSource:
    name = "yahoo_finance"
    base_url = "https://query2.finance.yahoo.com/v8/finance/chart"

    def __init__(self, timeout_seconds: int = 30) -> None:
        self.timeout_seconds = timeout_seconds

    def fetch_daily(self, security_code: str, range_: str = "1y") -> list[dict[str, Any]]:
        symbol = f"{security_code}.T"
        params = urllib.parse.urlencode(
            {
                "range": range_,
                "interval": "1d",
                "events": "history",
            }
        )
        request = urllib.request.Request(
            f"{self.base_url}/{urllib.parse.quote(symbol)}?{params}",
            headers={
                "User-Agent": "Mozilla/5.0 stock-visualize-composer/0.1",
                "Accept": "application/json",
            },
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise PriceSourceError(f"Yahoo Finance returned HTTP {exc.code} for {symbol}") from exc
        except urllib.error.URLError as exc:
            raise PriceSourceError(f"Yahoo Finance request failed for {symbol}: {exc}") from exc
        except json.JSONDecodeError as exc:
            raise PriceSourceError(f"Yahoo Finance returned invalid JSON for {symbol}") from exc

        chart = payload.get("chart", {})
        if chart.get("error"):
            raise PriceSourceError(f"Yahoo Finance error for {symbol}: {chart['error']}")
        result = (chart.get("result") or [None])[0]
        if not result:
            raise PriceSourceError(f"Yahoo Finance returned no result for {symbol}")

        timestamps = result.get("timestamp") or []
        indicators = result.get("indicators") or {}
        quote = (indicators.get("quote") or [None])[0] or {}
        adjclose = ((indicators.get("adjclose") or [None])[0] or {}).get("adjclose") or []
        rows: list[dict[str, Any]] = []
        for idx, timestamp in enumerate(timestamps):
            close = _item(quote.get("close"), idx)
            if close is None:
                continue
            rows.append(
                {
                    "date": datetime.fromtimestamp(int(timestamp), tz=timezone.utc).date().isoformat(),
                    "open": _item(quote.get("open"), idx),
                    "high": _item(quote.get("high"), idx),
                    "low": _item(quote.get("low"), idx),
                    "close": close,
                    "volume": _item(quote.get("volume"), idx),
                    "adjusted_close": _item(adjclose, idx) or close,
                }
            )
        if not rows:
            raise PriceSourceError(f"Yahoo Finance returned no usable daily bars for {symbol}")
        return rows


def update_prices_for_company(
    conn: sqlite3.Connection,
    security_code: str,
    *,
    range_: str = "1y",
    source_name: str = "yahoo_finance",
) -> dict[str, Any]:
    company = row_to_dict(
        conn.execute(
            "SELECT id, security_code, name FROM companies WHERE security_code = ? AND is_active = 1",
            (security_code,),
        ).fetchone()
    )
    if company is None:
        raise ValueError(f"Company not found: {security_code}")

    source = _source(source_name)
    started_at = utc_now()
    rows = source.fetch_daily(security_code, range_=range_)
    now = utc_now()
    for row in rows:
        conn.execute(
            """
            INSERT INTO price_bars
                (company_id, timeframe, date, open, high, low, close, volume,
                 adjusted_close, source, created_at, updated_at)
            VALUES (?, '1d', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id, timeframe, date, source) DO UPDATE SET
                open = excluded.open,
                high = excluded.high,
                low = excluded.low,
                close = excluded.close,
                volume = excluded.volume,
                adjusted_close = excluded.adjusted_close,
                updated_at = excluded.updated_at
            """,
            (
                company["id"],
                row["date"],
                row["open"],
                row["high"],
                row["low"],
                row["close"],
                row["volume"],
                row["adjusted_close"],
                source.name,
                now,
                now,
            ),
        )
    indicator_count = calculate_for_company(conn, int(company["id"]))
    write_update_log(
        conn,
        job_name="update_prices",
        source=source.name,
        status="success",
        message=f"{security_code}: imported {len(rows)} rows",
        metadata_json=json.dumps(
            {
                "security_code": security_code,
                "range": range_,
                "rows": len(rows),
                "latest_date": rows[-1]["date"],
                "indicator_rows": indicator_count,
            },
            ensure_ascii=False,
        ),
        started_at=started_at,
        finished_at=utc_now(),
    )
    return {
        "security_code": security_code,
        "source": source.name,
        "rows": len(rows),
        "latest_date": rows[-1]["date"],
        "indicator_rows": indicator_count,
    }


def update_prices_for_watchlist(
    conn: sqlite3.Connection,
    *,
    list_name: str | None = None,
    range_: str = "1y",
    source_name: str = "yahoo_finance",
    pause_seconds: float = 0.25,
) -> list[dict[str, Any]]:
    selected_list = list_name or get_setting(conn, "watchlist_default", "JPX400") or "JPX400"
    rows = conn.execute(
        """
        SELECT c.security_code
        FROM watchlists w
        JOIN companies c ON c.id = w.company_id
        WHERE w.is_active = 1 AND c.is_active = 1 AND w.list_name = ?
        ORDER BY w.priority DESC, c.security_code ASC
        """,
        (selected_list,),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for idx, row in enumerate(rows):
        if idx > 0 and pause_seconds > 0:
            time.sleep(pause_seconds)
        results.append(
            update_prices_for_company(
                conn,
                row["security_code"],
                range_=range_,
                source_name=source_name,
            )
        )
    return results


def delete_test_data(conn: sqlite3.Connection) -> dict[str, int]:
    deleted: dict[str, int] = {}
    deleted["sample_price_bars"] = conn.execute("DELETE FROM price_bars WHERE source = 'sample'").rowcount
    deleted["sample_disclosures"] = conn.execute("DELETE FROM disclosures WHERE source = 'sample'").rowcount
    deleted["mock_judgements"] = conn.execute("DELETE FROM ai_judgements WHERE model_provider = 'mock'").rowcount
    deleted["sample_logs"] = conn.execute(
        """
        DELETE FROM data_update_logs
        WHERE source IN ('sample', 'manual_or_sample')
           OR metadata_json LIKE '%MVPサンプル%'
        """
    ).rowcount
    write_update_log(
        conn,
        job_name="cleanup_test_data",
        source="sqlite",
        status="success",
        message="Deleted sample price bars, sample disclosures, and mock judgements",
        metadata_json=json.dumps(deleted, ensure_ascii=False),
    )
    return deleted


def _source(source_name: str) -> YahooFinanceChartSource:
    if source_name == "yahoo_finance":
        return YahooFinanceChartSource()
    raise ValueError(f"Unsupported price source: {source_name}")


def _item(values: Any, idx: int) -> float | None:
    if not isinstance(values, list) or idx >= len(values):
        return None
    value = values[idx]
    if value is None:
        return None
    return float(value)
