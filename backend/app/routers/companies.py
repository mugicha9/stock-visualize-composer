from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import row_to_dict, utc_now, write_update_log
from ..deps import get_db
from ..models import FetchCompanyDataRequest
from ..services.company_sources import (
    CompanySourceError,
    list_financials_for_company,
    list_news_for_company,
    update_disclosures_for_company,
    update_financials_for_company,
    update_news_for_company,
)
from ..services.global_news import GlobalNewsSourceError, list_global_news, update_global_news
from ..services.indicators import calculate_indicator_rows
from ..services.price_sources import PriceSourceError, update_prices_for_company


router = APIRouter(prefix="/companies", tags=["companies"])


@router.get("/search")
def search_companies(
    q: str = Query(default=""),
    limit: int = Query(default=20, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    like = f"%{q.strip()}%"
    if q.strip():
        rows = conn.execute(
            """
            SELECT id, security_code, name, market, sector, industry, fiscal_year_end, is_active
            FROM companies
            WHERE is_active = 1
              AND (security_code LIKE ? OR name LIKE ? OR industry LIKE ? OR market LIKE ?)
            ORDER BY security_code ASC
            LIMIT ?
            """,
            (like, like, like, like, limit),
        ).fetchall()
    else:
        rows = conn.execute(
            """
            SELECT id, security_code, name, market, sector, industry, fiscal_year_end, is_active
            FROM companies
            WHERE is_active = 1
            ORDER BY security_code ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(row) for row in rows]


@router.get("/{security_code}")
def get_company(
    security_code: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    company = row_to_dict(
        conn.execute(
            "SELECT * FROM companies WHERE security_code = ? AND is_active = 1",
            (security_code,),
        ).fetchone()
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    latest_price = row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM price_bars
            WHERE company_id = ? AND timeframe = '1d'
            ORDER BY date DESC
            LIMIT 1
            """,
            (company["id"],),
        ).fetchone()
    )
    latest_indicator = row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM technical_indicators
            WHERE company_id = ? AND timeframe = '1d'
            ORDER BY date DESC
            LIMIT 1
            """,
            (company["id"],),
        ).fetchone()
    )
    if latest_indicator and latest_indicator.get("features_json"):
        latest_indicator["features"] = json.loads(latest_indicator["features_json"])
    return {
        **company,
        "latest_price": latest_price,
        "latest_indicator": latest_indicator,
    }


@router.get("/{security_code}/prices")
def get_prices(
    security_code: str,
    timeframe: str = "1d",
    limit: int = Query(default=250, ge=1, le=2000),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    company_id = _company_id(conn, security_code)
    rows = conn.execute(
        """
        SELECT date, timeframe, open, high, low, close, volume, adjusted_close, source
        FROM price_bars
        WHERE company_id = ? AND timeframe = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (company_id, timeframe, limit),
    ).fetchall()
    return [dict(row) for row in reversed(rows)]


@router.get("/{security_code}/chart")
def get_chart(
    security_code: str,
    timeframe: str = "1d",
    limit: int = Query(default=250, ge=1, le=2000),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    company = row_to_dict(
        conn.execute(
            "SELECT * FROM companies WHERE security_code = ? AND is_active = 1",
            (security_code,),
        ).fetchone()
    )
    if company is None:
        raise HTTPException(status_code=404, detail="Company not found")
    if timeframe == "1d":
        rows = conn.execute(
            """
            SELECT
                p.date, p.open, p.high, p.low, p.close, p.volume,
                t.ma_5, t.ma_25, t.ma_75, t.volume_ma_5, t.volume_ma_25,
                t.trend_short, t.trend_middle, t.features_json
            FROM price_bars p
            LEFT JOIN technical_indicators t
              ON t.company_id = p.company_id
             AND t.timeframe = p.timeframe
             AND t.date = p.date
            WHERE p.company_id = ? AND p.timeframe = ?
            ORDER BY p.date DESC
            LIMIT ?
            """,
            (company["id"], timeframe, limit),
        ).fetchall()
        chart_rows = [dict(row) for row in reversed(rows)]
        for row in chart_rows:
            if row.get("features_json"):
                row["features"] = json.loads(row["features_json"])
    elif timeframe in {"1w", "1mo"}:
        daily_limit = limit * (7 if timeframe == "1w" else 31)
        rows = conn.execute(
            """
            SELECT company_id, timeframe, date, open, high, low, close, volume
            FROM price_bars
            WHERE company_id = ? AND timeframe = '1d'
            ORDER BY date DESC
            LIMIT ?
            """,
            (company["id"], daily_limit),
        ).fetchall()
        aggregated = _aggregate_bars([dict(row) for row in reversed(rows)], timeframe)
        indicators = calculate_indicator_rows(aggregated)
        by_date = {row["date"]: row for row in indicators}
        chart_rows = []
        for row in aggregated[-limit:]:
            indicator = by_date.get(row["date"], {})
            chart_rows.append(
                {
                    **row,
                    "ma_5": indicator.get("ma_5"),
                    "ma_25": indicator.get("ma_25"),
                    "ma_75": indicator.get("ma_75"),
                    "volume_ma_5": indicator.get("volume_ma_5"),
                    "volume_ma_25": indicator.get("volume_ma_25"),
                    "features_json": indicator.get("features_json"),
                    "features": json.loads(indicator["features_json"]) if indicator.get("features_json") else {},
                }
            )
    else:
        raise HTTPException(status_code=400, detail="Unsupported timeframe")
    return {
        "company": company,
        "timeframe": timeframe,
        "bars": chart_rows,
    }


@router.get("/{security_code}/indicators")
def get_indicators(
    security_code: str,
    timeframe: str = "1d",
    latest: bool = False,
    limit: int = Query(default=250, ge=1, le=2000),
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any] | list[dict[str, Any]]:
    company_id = _company_id(conn, security_code)
    if latest:
        row = conn.execute(
            """
            SELECT *
            FROM technical_indicators
            WHERE company_id = ? AND timeframe = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            (company_id, timeframe),
        ).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Indicators not found")
        item = dict(row)
        item["features"] = json.loads(item["features_json"]) if item.get("features_json") else {}
        return item

    rows = conn.execute(
        """
        SELECT *
        FROM technical_indicators
        WHERE company_id = ? AND timeframe = ?
        ORDER BY date DESC
        LIMIT ?
        """,
        (company_id, timeframe, limit),
    ).fetchall()
    items = [dict(row) for row in reversed(rows)]
    for item in items:
        item["features"] = json.loads(item["features_json"]) if item.get("features_json") else {}
    return items


@router.get("/{security_code}/financials")
def get_financials(
    security_code: str,
    limit: int = Query(default=5, ge=1, le=50),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        return list_financials_for_company(conn, security_code, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{security_code}/news")
def get_news(
    security_code: str,
    limit: int = Query(default=20, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    try:
        return list_news_for_company(conn, security_code, limit=limit)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/{security_code}/external-factors")
def get_external_factors(
    security_code: str,
    limit: int = Query(default=20, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    _company_id(conn, security_code)
    return list_global_news(conn, limit=limit)


@router.post("/{security_code}/fetch-data")
def fetch_company_data(
    security_code: str,
    payload: FetchCompanyDataRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    request = payload or FetchCompanyDataRequest()
    started_at = utc_now()
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    _company_id(conn, security_code)

    if request.include_prices:
        try:
            results["prices"] = update_prices_for_company(conn, security_code, range_=request.price_range)
        except (PriceSourceError, ValueError) as exc:
            errors["prices"] = str(exc)
    if request.include_financials:
        try:
            results["financials"] = update_financials_for_company(conn, security_code)
        except (CompanySourceError, ValueError) as exc:
            errors["financials"] = str(exc)
    if request.include_disclosures:
        try:
            results["disclosures"] = update_disclosures_for_company(conn, security_code)
        except (CompanySourceError, ValueError) as exc:
            errors["disclosures"] = str(exc)
    if request.include_news:
        try:
            results["news"] = update_news_for_company(conn, security_code, summarize=request.summarize_news)
        except (CompanySourceError, ValueError) as exc:
            errors["news"] = str(exc)
    if request.include_external_factors:
        try:
            results["external_factors"] = update_global_news(conn)
        except (GlobalNewsSourceError, ValueError) as exc:
            errors["external_factors"] = str(exc)

    status = "partial_success" if errors and results else "failed" if errors else "success"
    write_update_log(
        conn,
        job_name="fetch_company_data",
        source="mixed",
        status=status,
        message=f"{security_code}: {status}",
        metadata_json=json.dumps(
            {
                "security_code": security_code,
                "requested": request.model_dump(),
                "result_keys": list(results.keys()),
                "errors": errors,
            },
            ensure_ascii=False,
        ),
        started_at=started_at,
        finished_at=utc_now(),
    )
    return {"status": status, "security_code": security_code, "results": results, "errors": errors}


def _company_id(conn: sqlite3.Connection, security_code: str) -> int:
    row = conn.execute(
        "SELECT id FROM companies WHERE security_code = ? AND is_active = 1",
        (security_code,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return int(row["id"])


def _aggregate_bars(rows: list[dict[str, Any]], timeframe: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    order: list[str] = []
    for row in rows:
        if timeframe == "1w":
            import datetime as _dt

            parsed = _dt.date.fromisoformat(row["date"])
            iso_year, iso_week, _ = parsed.isocalendar()
            key = f"{iso_year}-W{iso_week:02d}"
        else:
            key = row["date"][:7]
        if key not in grouped:
            grouped[key] = []
            order.append(key)
        grouped[key].append(row)

    bars: list[dict[str, Any]] = []
    for key in order:
        group = grouped[key]
        first = group[0]
        last = group[-1]
        bars.append(
            {
                "company_id": first["company_id"],
                "timeframe": timeframe,
                "date": last["date"],
                "open": first["open"],
                "high": max(row["high"] for row in group if row["high"] is not None),
                "low": min(row["low"] for row in group if row["low"] is not None),
                "close": last["close"],
                "volume": sum(row["volume"] for row in group if row["volume"] is not None),
            }
        )
    return bars
