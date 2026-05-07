from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, Query

from ..deps import get_db
from ..services.global_news import list_global_news


router = APIRouter(prefix="/market-news", tags=["market-news"])


@router.get("")
def get_market_news(
    limit: int = Query(default=20, ge=1, le=100),
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    return list_global_news(conn, limit=limit)
