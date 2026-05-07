from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db
from ..models import RunJudgementRequest
from ..services.judgements import (
    build_external_advice_prompt,
    get_judgement_context,
    list_judgements,
    run_short_term_judgement,
)


router = APIRouter(tags=["ai_judgements"])


@router.get("/companies/{security_code}/ai-judgements")
def list_company_judgements(
    security_code: str,
    limit: int = 50,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    return list_judgements(conn, security_code=security_code, limit=limit)


@router.post("/companies/{security_code}/ai-judgements/run")
def run_company_judgement(
    security_code: str,
    payload: RunJudgementRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        return run_short_term_judgement(
            conn,
            security_code,
            provider_name=payload.provider if payload else None,
            model_name=payload.model_name if payload else None,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@router.get("/companies/{security_code}/ai-judgements/external-prompt")
def get_external_prompt(
    security_code: str,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        return build_external_advice_prompt(conn, security_code)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/ai-judgements/latest")
def list_latest_judgements(
    limit: int = 50,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    return list_judgements(conn, limit=limit)


@router.get("/ai-judgements/{judgement_id}/context")
def get_ai_judgement_context(
    judgement_id: int,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        return get_judgement_context(conn, judgement_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
