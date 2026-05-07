from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..database import utc_now
from ..deps import get_db
from ..models import DisclosureCreate
from ..services.information_dates import infer_information_date


router = APIRouter(prefix="/companies/{security_code}/disclosures", tags=["disclosures"])


@router.get("")
def list_disclosures(
    security_code: str,
    limit: int = 20,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    company_id = _company_id(conn, security_code)
    rows = conn.execute(
        """
        SELECT *
        FROM disclosures
        WHERE company_id = ?
        ORDER BY COALESCE(information_date, substr(published_at, 1, 10)) DESC, id DESC
        LIMIT ?
        """,
        (company_id, limit),
    ).fetchall()
    return [dict(row) for row in rows]


@router.post("")
def create_disclosure(
    security_code: str,
    payload: DisclosureCreate,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    company_id = _company_id(conn, security_code)
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO disclosures
            (company_id, title, document_type, published_at, information_date, source, url, local_path,
             summary, importance_score, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?, ?)
        """,
        (
            company_id,
            payload.title,
            payload.document_type,
            payload.published_at,
            infer_information_date(
                title=payload.title,
                published_at=payload.published_at,
                url=payload.url,
                created_at=now,
            ),
            payload.source,
            payload.url,
            payload.summary,
            payload.importance_score,
            now,
            now,
        ),
    )
    row = conn.execute("SELECT * FROM disclosures WHERE id = ?", (cur.lastrowid,)).fetchone()
    return dict(row)


def _company_id(conn: sqlite3.Connection, security_code: str) -> int:
    row = conn.execute(
        "SELECT id FROM companies WHERE security_code = ? AND is_active = 1",
        (security_code,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return int(row["id"])
