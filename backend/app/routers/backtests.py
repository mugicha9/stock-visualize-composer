from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..deps import get_db
from ..models import BacktestPeriodInfoRequest, BacktestRequest
from ..services.backtests import fetch_backtest_period_info, run_backtest


router = APIRouter(prefix="/backtests", tags=["backtests"])


@router.post("/run")
def run_backtest_endpoint(
    payload: BacktestRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        return run_backtest(conn, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.post("/fetch-period-info")
def fetch_period_info_endpoint(
    payload: BacktestPeriodInfoRequest,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        return fetch_backtest_period_info(conn, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
