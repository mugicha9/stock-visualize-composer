from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..config import APP_SETTINGS_PATH
from ..database import upsert_setting
from ..deps import get_db


router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("")
def list_settings(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    rows = conn.execute(
        """
        SELECT key, value, updated_at
        FROM app_settings
        ORDER BY key ASC
        """
    ).fetchall()
    return {"settings": [dict(row) for row in rows], "config_path": str(APP_SETTINGS_PATH)}


@router.put("/{key}")
def update_setting(
    key: str,
    payload: dict[str, str],
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    value = payload.get("value", "")
    try:
        return upsert_setting(conn, key, value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
