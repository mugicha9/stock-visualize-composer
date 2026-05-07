from __future__ import annotations

import json
import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_setting, row_to_dict, utc_now, write_update_log
from ..deps import get_db
from ..models import JobRequest
from ..services.company_sources import (
    CompanySourceError,
    update_disclosures_for_company,
    update_financials_for_company,
    update_news_for_company,
)
from ..services.content_summaries import summarize_existing_news_for_company
from ..services.global_news import GlobalNewsSourceError, update_global_news
from ..services.indicators import calculate_for_all_companies, calculate_for_company
from ..services.judgements import run_short_term_judgement
from ..services.price_sources import PriceSourceError, update_prices_for_company, update_prices_for_watchlist


router = APIRouter(prefix="/jobs", tags=["jobs"])


@router.post("/update-prices")
def update_prices(
    payload: JobRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    try:
        if payload and payload.security_code:
            results = [
                update_prices_for_company(
                    conn,
                    payload.security_code,
                    range_=payload.range,
                    source_name=payload.source,
                )
            ]
        else:
            results = update_prices_for_watchlist(
                conn,
                list_name=payload.list_name if payload else None,
                range_=payload.range if payload else "1y",
                source_name=payload.source if payload else "yahoo_finance",
            )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PriceSourceError as exc:
        write_update_log(
            conn,
            job_name="update_prices",
            source=payload.source if payload else "yahoo_finance",
            status="failed",
            message=str(exc),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {"status": "success", "count": len(results), "results": results}


@router.post("/calculate-indicators")
def calculate_indicators(
    payload: JobRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    started_at = utc_now()
    if payload and payload.security_code:
        company = row_to_dict(
            conn.execute(
                "SELECT id FROM companies WHERE security_code = ? AND is_active = 1",
                (payload.security_code,),
            ).fetchone()
        )
        if company is None:
            raise HTTPException(status_code=404, detail="Company not found")
        count = calculate_for_company(conn, int(company["id"]))
    else:
        count = calculate_for_all_companies(conn)
    log_id = write_update_log(
        conn,
        job_name="calculate_technical_indicators",
        source="sqlite",
        status="success",
        message=f"Calculated {count} indicator rows",
        metadata_json=json.dumps({"rows": count}, ensure_ascii=False),
        started_at=started_at,
        finished_at=utc_now(),
    )
    return {"status": "success", "rows": count, "log_id": log_id}


@router.post("/update-disclosures")
def update_disclosures(
    payload: JobRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return _run_company_source_job(
        conn,
        payload=payload,
        job_name="update_disclosures",
        source="tdnet_via_yahoo_finance",
        updater=update_disclosures_for_company,
    )


@router.post("/update-news")
def update_news(
    payload: JobRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return _run_company_source_job(
        conn,
        payload=payload,
        job_name="update_news",
        source="yahoo_finance_news",
        updater=update_news_for_company,
    )


@router.post("/summarize-news")
def summarize_news(
    payload: JobRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return _run_company_source_job(
        conn,
        payload=payload,
        job_name="summarize_news",
        source=get_setting(conn, "news_summary_provider", "llama_cpp") or "llama_cpp",
        updater=lambda job_conn, code: summarize_existing_news_for_company(job_conn, code, limit=20, force=False),
    )


@router.post("/update-company-info")
def update_company_info(
    payload: JobRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    return _run_company_source_job(
        conn,
        payload=payload,
        job_name="update_company_info",
        source="yahoo_finance_japan",
        updater=update_financials_for_company,
    )


@router.post("/update-external-factors")
def update_external_factors(
    payload: JobRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    del payload
    return update_global_market_news(conn)


@router.post("/update-global-news")
def update_global_market_news(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    started_at = utc_now()
    try:
        limit = int(get_setting(conn, "global_news_fetch_limit_per_source", "40") or "40")
        result = update_global_news(conn, limit_per_source=limit)
    except GlobalNewsSourceError as exc:
        log_id = write_update_log(
            conn,
            job_name="update_global_news",
            source="official_rss",
            status="failed",
            message=str(exc),
            started_at=started_at,
            finished_at=utc_now(),
        )
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    log_id = write_update_log(
        conn,
        job_name="update_global_news",
        source="official_rss",
        status="success" if not result["errors"] else "partial_success",
        message=f"{result['count']} shared news items updated",
        metadata_json=json.dumps(result, ensure_ascii=False),
        started_at=started_at,
        finished_at=utc_now(),
    )
    return {"status": "success" if not result["errors"] else "partial_success", "log_id": log_id, **result}


@router.post("/update-watchlist-data")
def update_watchlist_data(
    payload: JobRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    started_at = utc_now()
    codes = _target_security_codes(conn, payload)
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, dict[str, str]] = {}
    for security_code in codes:
        item: dict[str, Any] = {}
        item_errors: dict[str, str] = {}
        for key, updater in (
            (
                "prices",
                lambda code: update_prices_for_company(
                    conn,
                    code,
                    range_=payload.range if payload else "1y",
                    source_name=payload.source if payload else "yahoo_finance",
                ),
            ),
            ("financials", lambda code: update_financials_for_company(conn, code)),
            ("disclosures", lambda code: len(update_disclosures_for_company(conn, code))),
            ("news", lambda code: len(update_news_for_company(conn, code))),
        ):
            try:
                item[key] = _summarize_update_result(key, updater(security_code))
            except (PriceSourceError, CompanySourceError, ValueError) as exc:
                item_errors[key] = str(exc)
        results[security_code] = item
        if item_errors:
            errors[security_code] = item_errors
    status = "partial_success" if errors and results else "failed" if errors else "success"
    log_id = write_update_log(
        conn,
        job_name="update_watchlist_data",
        source="mixed",
        status=status,
        message=f"{len(results)} processed, {len(errors)} with errors",
        metadata_json=json.dumps({"security_codes": codes, "errors": errors}, ensure_ascii=False),
        started_at=started_at,
        finished_at=utc_now(),
    )
    return {
        "status": status,
        "count": len(results),
        "error_count": len(errors),
        "results": results,
        "errors": errors,
        "log_id": log_id,
    }


@router.post("/run-short-term-judgements")
def run_short_term_judgements(
    payload: JobRequest | None = None,
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    started_at = utc_now()
    codes = _target_security_codes(conn, payload)
    results: list[dict[str, Any]] = []
    errors: dict[str, str] = {}
    for security_code in codes:
        try:
            results.append(
                run_short_term_judgement(
                    conn,
                    security_code,
                    provider_name=payload.provider if payload else None,
                )
            )
        except (ValueError, RuntimeError) as exc:
            errors[security_code] = str(exc)
    status = "partial_success" if errors and results else "failed" if errors else "success"
    log_id = write_update_log(
        conn,
        job_name="run_short_term_judgements",
        source=payload.provider if payload and payload.provider else get_setting(conn, "default_llm_provider", "mock"),
        status=status,
        message=f"{len(results)} succeeded, {len(errors)} failed",
        metadata_json=json.dumps({"security_codes": codes, "errors": errors}, ensure_ascii=False),
        started_at=started_at,
        finished_at=utc_now(),
    )
    return {"status": status, "count": len(results), "errors": errors, "judgements": results, "log_id": log_id}


@router.get("/logs")
def list_logs(
    limit: int = 100,
    conn: sqlite3.Connection = Depends(get_db),
) -> list[dict[str, Any]]:
    rows = conn.execute(
        """
        SELECT *
        FROM data_update_logs
        ORDER BY started_at DESC, id DESC
        LIMIT ?
        """,
        (limit,),
    ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        if item.get("metadata_json"):
            try:
                item["metadata"] = json.loads(item["metadata_json"])
            except json.JSONDecodeError:
                item["metadata"] = None
    return items


def _run_company_source_job(
    conn: sqlite3.Connection,
    *,
    payload: JobRequest | None,
    job_name: str,
    source: str,
    updater: Any,
) -> dict[str, Any]:
    started_at = utc_now()
    codes = _target_security_codes(conn, payload)
    results: list[Any] = []
    errors: dict[str, str] = {}
    for security_code in codes:
        try:
            results.append(updater(conn, security_code))
        except (CompanySourceError, ExternalFactorSourceError, ValueError) as exc:
            errors[security_code] = str(exc)
    status = "partial_success" if errors and results else "failed" if errors else "success"
    log_id = write_update_log(
        conn,
        job_name=job_name,
        source=source,
        status=status,
        message=f"{len(results)} succeeded, {len(errors)} failed",
        metadata_json=json.dumps({"security_codes": codes, "errors": errors}, ensure_ascii=False),
        started_at=started_at,
        finished_at=utc_now(),
    )
    return {"status": status, "count": len(results), "results": results, "errors": errors, "log_id": log_id}


def _summarize_update_result(key: str, value: Any) -> Any:
    if key == "financials" and isinstance(value, dict):
        return {
            "id": value.get("id"),
            "as_of": value.get("as_of"),
            "next_earnings_date": value.get("next_earnings_date"),
        }
    return value


def _target_security_codes(conn: sqlite3.Connection, payload: JobRequest | None) -> list[str]:
    if payload and payload.security_code:
        return [payload.security_code]
    selected_list = (payload.list_name if payload else None) or get_setting(conn, "watchlist_default", "JPX400") or "JPX400"
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
    return [row["security_code"] for row in rows]
