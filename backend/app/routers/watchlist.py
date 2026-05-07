from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query

from ..database import get_setting, row_to_dict, utc_now
from ..deps import get_db
from ..models import WatchlistCreate
from ..services.company_sources import (
    CompanySourceError,
    update_disclosures_for_company,
    update_financials_for_company,
    update_news_for_company,
)
from ..services.judgements import latest_judgement_for_company
from ..services.price_sources import PriceSourceError, update_prices_for_company


router = APIRouter(prefix="/watchlist", tags=["watchlist"])


@router.get("")
def list_watchlist(
    list_name: str | None = Query(default=None),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    selected_list = list_name or get_setting(conn, "watchlist_default", "JPX400") or "JPX400"
    rows = conn.execute(
        """
        SELECT
            w.id AS watchlist_id,
            w.list_name,
            w.memo,
            w.priority,
            w.created_at AS watchlist_created_at,
            c.*
        FROM watchlists w
        JOIN companies c ON c.id = w.company_id
        WHERE w.is_active = 1 AND c.is_active = 1 AND w.list_name = ?
        ORDER BY w.priority DESC, c.security_code ASC
        """,
        (selected_list,),
    ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        item["latest_price"] = _latest_price(conn, int(item["id"]))
        latest_indicator = _latest_indicator(conn, int(item["id"]))
        if latest_indicator and latest_indicator.get("features_json"):
            latest_indicator["features"] = json.loads(latest_indicator["features_json"])
        item["latest_indicator"] = latest_indicator
        item["latest_judgement"] = latest_judgement_for_company(conn, int(item["id"]))
        item["latest_disclosure"] = _latest_disclosure(conn, int(item["id"]))
        result.append(item)
    return result


@router.post("")
def add_watchlist(
    payload: WatchlistCreate,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    now = utc_now()
    company = row_to_dict(
        conn.execute(
            "SELECT * FROM companies WHERE security_code = ?",
            (payload.security_code,),
        ).fetchone()
    )
    if company is None:
        cur = conn.execute(
            """
            INSERT INTO companies
                (security_code, name, market, sector, industry, fiscal_year_end, is_active, created_at, updated_at)
            VALUES (?, ?, NULL, NULL, NULL, NULL, 1, ?, ?)
            """,
            (
                payload.security_code,
                payload.name or f"未登録銘柄 {payload.security_code}",
                now,
                now,
            ),
        )
        company_id = int(cur.lastrowid)
    else:
        company_id = int(company["id"])

    cur = conn.execute(
        """
        INSERT INTO watchlists
            (company_id, list_name, memo, priority, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, 1, ?, ?)
        ON CONFLICT(company_id, list_name) DO UPDATE SET
            memo = excluded.memo,
            priority = excluded.priority,
            is_active = 1,
            updated_at = excluded.updated_at
        """,
        (company_id, payload.list_name, payload.memo, payload.priority, now, now),
    )
    watchlist_id = cur.lastrowid
    data_update: dict[str, Any] = {}
    data_update_errors: dict[str, str] = {}
    if payload.fetch_prices:
        try:
            data_update["prices"] = update_prices_for_company(conn, payload.security_code, range_=payload.price_range)
        except (PriceSourceError, ValueError) as exc:
            data_update_errors["prices"] = str(exc)
    if payload.fetch_context:
        for key, updater in (
            ("financials", update_financials_for_company),
            ("disclosures", update_disclosures_for_company),
            ("news", lambda update_conn, code: update_news_for_company(update_conn, code, summarize=payload.summarize_news)),
        ):
            try:
                data_update[key] = updater(conn, payload.security_code)
            except (CompanySourceError, ValueError) as exc:
                data_update_errors[key] = str(exc)

    row = conn.execute(
        """
        SELECT w.id AS watchlist_id, w.list_name, w.memo, w.priority, c.*
        FROM watchlists w
        JOIN companies c ON c.id = w.company_id
        WHERE w.company_id = ? AND w.list_name = ?
        """,
        (company_id, payload.list_name),
    ).fetchone()
    item = dict(row)
    item["watchlist_id"] = item["watchlist_id"] or watchlist_id
    if data_update or data_update_errors:
        item["data_update"] = data_update
        item["data_update_errors"] = data_update_errors
    return item


@router.delete("/{watchlist_id}")
def delete_watchlist(
    watchlist_id: int,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    now = utc_now()
    cur = conn.execute(
        """
        UPDATE watchlists
        SET is_active = 0, updated_at = ?
        WHERE id = ?
        """,
        (now, watchlist_id),
    )
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="Watchlist item not found")
    return {"deleted": True, "watchlist_id": watchlist_id}


def _latest_price(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM price_bars
            WHERE company_id = ? AND timeframe = '1d'
            ORDER BY date DESC
            LIMIT 1
            """,
            (company_id,),
        ).fetchone()
    )


def _latest_indicator(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            """
            SELECT *
            FROM technical_indicators
            WHERE company_id = ? AND timeframe = '1d'
            ORDER BY date DESC
            LIMIT 1
            """,
            (company_id,),
        ).fetchone()
    )


def _latest_disclosure(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    return row_to_dict(
        conn.execute(
            """
            SELECT id, title, document_type, published_at, information_date, source, url, summary, importance_score
            FROM disclosures
            WHERE company_id = ?
            ORDER BY COALESCE(information_date, substr(published_at, 1, 10)) DESC, id DESC
            LIMIT 1
            """,
            (company_id,),
        ).fetchone()
    )
