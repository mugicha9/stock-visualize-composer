from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..database import utc_now
from ..deps import get_db
from ..models import DisclosureCreate
from ..services.information_dates import infer_information_date
from ..services.source_events import list_company_events, record_event_triage, upsert_event_summary, upsert_source_event


router = APIRouter(prefix="/companies/{security_code}/disclosures", tags=["disclosures"])


@router.get("")
def list_disclosures(
    security_code: str,
    limit: int = 20,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    company_id = _company_id(conn, security_code)
    return [_disclosure_item(event) for event in list_company_events(conn, company_id, event_types={"disclosure"}, limit=limit)]


@router.post("")
def create_disclosure(
    security_code: str,
    payload: DisclosureCreate,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    company_id = _company_id(conn, security_code)
    now = utc_now()
    information_date = infer_information_date(
        title=payload.title,
        published_at=payload.published_at,
        url=payload.url,
        created_at=now,
    )
    event = upsert_source_event(
        conn,
        scope="company",
        event_type="disclosure",
        company_id=company_id,
        title=payload.title,
        information_date=information_date,
        published_at=payload.published_at,
        source=payload.source,
        provider="manual",
        url=payload.url,
        metadata={
            "document_type": payload.document_type,
            "summary": payload.summary,
            "importance_score": payload.importance_score,
        },
        raw_payload=payload.model_dump(),
    )
    record_event_triage(
        conn,
        source_event_id=int(event["id"]),
        company_id=company_id,
        action="must_include",
        relevance_score=payload.importance_score,
        materiality_score=payload.importance_score,
        reason="手動登録された開示",
        model_name="manual",
        prompt_version="manual",
    )
    if payload.summary:
        upsert_event_summary(
            conn,
            source_event_id=int(event["id"]),
            company_id=company_id,
            summary_text=payload.summary,
            summary_type="manual",
            model_name="manual",
        )
    return _disclosure_item(event)


def _company_id(conn: sqlite3.Connection, security_code: str) -> int:
    row = conn.execute(
        "SELECT id FROM companies WHERE security_code = ? AND is_active = 1",
        (security_code,),
    ).fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Company not found")
    return int(row["id"])


def _disclosure_item(event: dict[str, Any]) -> dict[str, Any]:
    metadata = event.get("metadata") or {}
    return {
        "id": event["id"],
        "source_event_id": event["id"],
        "title": event.get("title"),
        "document_type": metadata.get("document_type"),
        "published_at": event.get("published_at"),
        "information_date": event.get("information_date"),
        "source": event.get("source"),
        "url": event.get("url"),
        "summary": event.get("summary"),
        "importance_score": metadata.get("importance_score"),
    }
