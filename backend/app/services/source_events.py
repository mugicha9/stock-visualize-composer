from __future__ import annotations

import hashlib
import json
import sqlite3
from typing import Any

from ..database import utc_now


COMPANY_EVENT_TYPES = {"company_news", "disclosure"}
GLOBAL_EVENT_TYPES = {"global_news"}


def upsert_source_event(
    conn: sqlite3.Connection,
    *,
    scope: str,
    event_type: str,
    title: str,
    company_id: int | None = None,
    information_date: str | None = None,
    published_at: str | None = None,
    source: str | None = None,
    provider: str | None = None,
    url: str | None = None,
    content_text: str | None = None,
    metadata: dict[str, Any] | None = None,
    raw_payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    normalized_title = _clean(title)
    event_key = _event_key(
        scope=scope,
        event_type=event_type,
        company_id=company_id,
        source=source,
        url=url,
        title=normalized_title,
        information_date=information_date,
        published_at=published_at,
    )
    now = utc_now()
    conn.execute(
        """
        INSERT INTO source_events
            (event_key, scope, company_id, event_type, title, information_date, published_at,
             source, provider, url, content_text, content_hash, metadata_json, raw_payload_json,
             created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(event_key) DO UPDATE SET
            title = excluded.title,
            information_date = excluded.information_date,
            published_at = excluded.published_at,
            provider = excluded.provider,
            url = excluded.url,
            content_text = COALESCE(excluded.content_text, source_events.content_text),
            content_hash = COALESCE(excluded.content_hash, source_events.content_hash),
            metadata_json = excluded.metadata_json,
            raw_payload_json = excluded.raw_payload_json,
            updated_at = excluded.updated_at
        """,
        (
            event_key,
            scope,
            company_id,
            event_type,
            normalized_title,
            information_date,
            published_at,
            source,
            provider,
            url,
            _clip(content_text),
            _hash(content_text),
            json.dumps(metadata or {}, ensure_ascii=False),
            json.dumps(raw_payload or {}, ensure_ascii=False),
            now,
            now,
        ),
    )
    row = conn.execute("SELECT * FROM source_events WHERE event_key = ?", (event_key,)).fetchone()
    return _event_row(row)


def record_event_triage(
    conn: sqlite3.Connection,
    *,
    source_event_id: int,
    company_id: int | None,
    action: str,
    relevance_score: float | None = None,
    materiality_score: float | None = None,
    reason: str | None = None,
    model_name: str | None = None,
    prompt_version: str | None = None,
) -> dict[str, Any]:
    triage_key = _triage_key(source_event_id, company_id)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO event_triage
            (triage_key, source_event_id, company_id, action, relevance_score, materiality_score,
             reason, model_name, prompt_version, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(triage_key) DO UPDATE SET
            action = excluded.action,
            relevance_score = excluded.relevance_score,
            materiality_score = excluded.materiality_score,
            reason = excluded.reason,
            model_name = excluded.model_name,
            prompt_version = excluded.prompt_version,
            updated_at = excluded.updated_at
        """,
        (
            triage_key,
            source_event_id,
            company_id,
            action,
            _clamp(relevance_score),
            _clamp(materiality_score),
            reason,
            model_name,
            prompt_version,
            now,
            now,
        ),
    )
    row = conn.execute("SELECT * FROM event_triage WHERE triage_key = ?", (triage_key,)).fetchone()
    return dict(row) if row else {}


def upsert_event_summary(
    conn: sqlite3.Connection,
    *,
    source_event_id: int,
    company_id: int | None,
    summary_text: str,
    summary_type: str = "llm_compressed",
    prompt_version: str | None = None,
    model_name: str | None = None,
    language: str = "ja",
    structured: dict[str, Any] | None = None,
) -> dict[str, Any]:
    summary_key = _summary_key(source_event_id, company_id, summary_type, prompt_version, model_name)
    now = utc_now()
    conn.execute(
        """
        INSERT INTO event_summaries
            (summary_key, source_event_id, company_id, summary_type, prompt_version, model_name,
             language, summary_text, structured_json, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(summary_key) DO UPDATE SET
            summary_text = excluded.summary_text,
            structured_json = excluded.structured_json,
            updated_at = excluded.updated_at
        """,
        (
            summary_key,
            source_event_id,
            company_id,
            summary_type,
            prompt_version,
            model_name,
            language,
            summary_text,
            json.dumps(structured or {}, ensure_ascii=False),
            now,
            now,
        ),
    )
    row = conn.execute("SELECT * FROM event_summaries WHERE summary_key = ?", (summary_key,)).fetchone()
    return dict(row) if row else {}


def list_company_events(
    conn: sqlite3.Connection,
    company_id: int,
    *,
    event_types: set[str] | None = None,
    as_of: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    selected_types = event_types or COMPANY_EVENT_TYPES
    placeholders = ",".join("?" for _ in selected_types)
    params: list[Any] = [company_id, company_id, *sorted(selected_types)]
    date_filter = ""
    if as_of:
        date_filter = "AND e.information_date IS NOT NULL AND e.information_date <= ?"
        params.append(as_of)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT e.*, t.action AS triage_action, t.relevance_score, t.materiality_score,
               t.reason AS selection_reason, s.summary_text, s.structured_json
        FROM source_events e
        LEFT JOIN event_triage t
          ON t.source_event_id = e.id
         AND t.triage_key = ('ev:' || e.id || ':co:' || ?)
        LEFT JOIN event_summaries s
          ON s.id = (
              SELECT es.id
              FROM event_summaries es
              WHERE es.source_event_id = e.id
                AND (es.company_id = e.company_id OR es.company_id IS NULL)
              ORDER BY es.updated_at DESC, es.id DESC
              LIMIT 1
          )
        WHERE e.company_id = ?
          AND e.event_type IN ({placeholders})
          {date_filter}
          AND COALESCE(t.action, 'title_only') != 'ignore'
        ORDER BY e.information_date DESC, e.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_inflate_event(row) for row in rows]


def list_global_events(
    conn: sqlite3.Connection,
    *,
    as_of: str | None = None,
    limit: int = 50,
    company_id: int | None = None,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    triage_join = ""
    if company_id is not None:
        triage_join = "AND t.triage_key = ('ev:' || e.id || ':co:' || ?)"
        params.append(company_id)
    date_filter = ""
    if as_of:
        date_filter = "AND e.information_date IS NOT NULL AND e.information_date <= ?"
        params.append(as_of)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT e.*, t.action AS triage_action, t.relevance_score, t.materiality_score,
               t.reason AS selection_reason, s.summary_text, s.structured_json
        FROM source_events e
        LEFT JOIN event_triage t
          ON t.source_event_id = e.id
         {triage_join}
        LEFT JOIN event_summaries s
          ON s.id = (
              SELECT es.id
              FROM event_summaries es
              WHERE es.source_event_id = e.id
              ORDER BY es.updated_at DESC, es.id DESC
              LIMIT 1
          )
        WHERE e.scope = 'global'
          AND e.event_type = 'global_news'
          {date_filter}
          AND COALESCE(t.action, 'summarize') != 'ignore'
        ORDER BY e.information_date DESC, e.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_inflate_event(row) for row in rows]


def list_important_company_events(
    conn: sqlite3.Connection,
    company_id: int,
    *,
    event_types: set[str] | None = None,
    as_of: str | None = None,
    lookback_days: int = 365,
    limit: int = 20,
    exclude_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    selected_types = event_types or COMPANY_EVENT_TYPES
    placeholders = ",".join("?" for _ in selected_types)
    exclude_ids = exclude_ids or set()
    exclude_clause = ""
    params: list[Any] = [company_id, company_id, *sorted(selected_types)]
    if as_of:
        params.extend([as_of, as_of, f"-{max(1, lookback_days)} days"])
        date_filter = "AND e.information_date IS NOT NULL AND e.information_date <= ? AND e.information_date >= date(?, ?)"
    else:
        date_filter = "AND e.information_date IS NOT NULL"
    if exclude_ids:
        exclude_clause = f"AND e.id NOT IN ({','.join('?' for _ in exclude_ids)})"
        params.extend(sorted(exclude_ids))
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT e.*, t.action AS triage_action, t.relevance_score, t.materiality_score,
               t.reason AS selection_reason, s.summary_text, s.structured_json
        FROM source_events e
        LEFT JOIN event_triage t
          ON t.source_event_id = e.id
         AND t.triage_key = ('ev:' || e.id || ':co:' || ?)
        LEFT JOIN event_summaries s
          ON s.id = (
              SELECT es.id
              FROM event_summaries es
              WHERE es.source_event_id = e.id
                AND (es.company_id = e.company_id OR es.company_id IS NULL)
              ORDER BY es.updated_at DESC, es.id DESC
              LIMIT 1
          )
        WHERE e.company_id = ?
          AND e.event_type IN ({placeholders})
          {date_filter}
          {exclude_clause}
          AND COALESCE(t.action, 'title_only') IN ('must_include', 'summarize')
        ORDER BY
          CASE COALESCE(t.action, '') WHEN 'must_include' THEN 3 WHEN 'summarize' THEN 2 ELSE 1 END DESC,
          COALESCE(t.materiality_score, t.relevance_score, 0) DESC,
          e.information_date DESC,
          e.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_inflate_event(row) for row in rows]


def list_important_global_events(
    conn: sqlite3.Connection,
    *,
    company_id: int | None = None,
    as_of: str | None = None,
    lookback_days: int = 365,
    limit: int = 20,
    exclude_ids: set[int] | None = None,
) -> list[dict[str, Any]]:
    exclude_ids = exclude_ids or set()
    params: list[Any] = []
    company_join = ""
    company_action = "NULL"
    company_relevance = "NULL"
    company_materiality = "NULL"
    company_reason = "NULL"
    if company_id is not None:
        company_join = """
        LEFT JOIN event_triage tc
          ON tc.source_event_id = e.id
         AND tc.triage_key = ('ev:' || e.id || ':co:' || ?)
        """
        company_action = "tc.action"
        company_relevance = "tc.relevance_score"
        company_materiality = "tc.materiality_score"
        company_reason = "tc.reason"
        params.append(company_id)
    if as_of:
        params.extend([as_of, as_of, f"-{max(1, lookback_days)} days"])
        date_filter = "AND e.information_date IS NOT NULL AND e.information_date <= ? AND e.information_date >= date(?, ?)"
    else:
        date_filter = "AND e.information_date IS NOT NULL"
    exclude_clause = ""
    if exclude_ids:
        exclude_clause = f"AND e.id NOT IN ({','.join('?' for _ in exclude_ids)})"
        params.extend(sorted(exclude_ids))
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT e.*,
               COALESCE({company_action}, tg.action) AS triage_action,
               COALESCE({company_relevance}, tg.relevance_score) AS relevance_score,
               COALESCE({company_materiality}, tg.materiality_score) AS materiality_score,
               COALESCE({company_reason}, tg.reason) AS selection_reason,
               s.summary_text, s.structured_json
        FROM source_events e
        {company_join}
        LEFT JOIN event_triage tg
          ON tg.source_event_id = e.id
         AND tg.triage_key = ('ev:' || e.id || ':co:global')
        LEFT JOIN event_summaries s
          ON s.id = (
              SELECT es.id
              FROM event_summaries es
              WHERE es.source_event_id = e.id
              ORDER BY es.updated_at DESC, es.id DESC
              LIMIT 1
          )
        WHERE e.scope = 'global'
          AND e.event_type = 'global_news'
          {date_filter}
          {exclude_clause}
          AND COALESCE({company_action}, tg.action, 'summarize') IN ('must_include', 'summarize')
        ORDER BY
          CASE COALESCE({company_action}, tg.action, '') WHEN 'must_include' THEN 3 WHEN 'summarize' THEN 2 ELSE 1 END DESC,
          COALESCE({company_materiality}, {company_relevance}, tg.materiality_score, tg.relevance_score, 0) DESC,
          e.information_date DESC,
          e.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_inflate_event(row) for row in rows]


def latest_event_summary(conn: sqlite3.Connection, source_event_id: int, company_id: int | None = None) -> str | None:
    params: list[Any] = [source_event_id]
    company_filter = ""
    if company_id is not None:
        company_filter = "AND (company_id = ? OR company_id IS NULL)"
        params.append(company_id)
    row = conn.execute(
        f"""
        SELECT summary_text
        FROM event_summaries
        WHERE source_event_id = ?
          {company_filter}
        ORDER BY company_id IS NULL ASC, updated_at DESC, id DESC
        LIMIT 1
        """,
        params,
    ).fetchone()
    return str(row["summary_text"]) if row else None


def source_event_counts(
    conn: sqlite3.Connection,
    *,
    company_id: int | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    params: list[Any] = []
    filters: list[str] = ["information_date IS NOT NULL"]
    if company_id is not None:
        filters.append("(company_id = ? OR scope = 'global')")
        params.append(company_id)
    if start_date:
        filters.append("information_date >= ?")
        params.append(start_date)
    if end_date:
        filters.append("information_date <= ?")
        params.append(end_date)
    row = conn.execute(
        f"""
        SELECT
            COUNT(*) AS available,
            MIN(information_date) AS earliest_date,
            MAX(information_date) AS latest_date,
            SUM(CASE WHEN event_type = 'company_news' THEN 1 ELSE 0 END) AS company_news,
            SUM(CASE WHEN event_type = 'disclosure' THEN 1 ELSE 0 END) AS disclosures,
            SUM(CASE WHEN event_type = 'global_news' THEN 1 ELSE 0 END) AS global_news
        FROM source_events
        WHERE {' AND '.join(filters)}
        """,
        params,
    ).fetchone()
    missing_params: list[Any] = []
    missing_filter = ""
    if company_id is not None:
        missing_filter = "WHERE (company_id = ? OR scope = 'global') AND (information_date IS NULL OR information_date = '')"
        missing_params.append(company_id)
    else:
        missing_filter = "WHERE information_date IS NULL OR information_date = ''"
    missing = conn.execute(f"SELECT COUNT(*) AS missing FROM source_events {missing_filter}", missing_params).fetchone()
    return {
        "available": int(row["available"] if row else 0),
        "earliest_date": row["earliest_date"] if row else None,
        "latest_date": row["latest_date"] if row else None,
        "company_news": int(row["company_news"] or 0) if row else 0,
        "disclosures": int(row["disclosures"] or 0) if row else 0,
        "global_news": int(row["global_news"] or 0) if row else 0,
        "missing_information_date": int(missing["missing"] if missing else 0),
    }


def _event_row(row: sqlite3.Row | None) -> dict[str, Any]:
    return _inflate_event(row) if row else {}


def _inflate_event(row: sqlite3.Row) -> dict[str, Any]:
    item = dict(row)
    metadata = _loads(item.get("metadata_json"))
    structured = _loads(item.get("structured_json"))
    item["metadata"] = metadata
    item["structured_summary"] = structured
    item["summary"] = item.get("summary_text") or metadata.get("summary")
    item["document_type"] = metadata.get("document_type")
    item["category"] = metadata.get("category")
    item["importance_score"] = metadata.get("importance_score")
    item["keyword_hits"] = metadata.get("keyword_hits")
    return item


def _event_key(
    *,
    scope: str,
    event_type: str,
    company_id: int | None,
    source: str | None,
    url: str | None,
    title: str,
    information_date: str | None,
    published_at: str | None,
) -> str:
    if url:
        material = ["url", scope, event_type, str(company_id or ""), str(source or ""), url.strip()]
    else:
        material = ["title", scope, event_type, str(company_id or ""), str(source or ""), title, str(information_date or published_at or "")]
    return hashlib.sha256("\x1f".join(material).encode("utf-8")).hexdigest()


def _triage_key(source_event_id: int, company_id: int | None) -> str:
    return f"ev:{source_event_id}:co:{company_id if company_id is not None else 'global'}"


def _summary_key(
    source_event_id: int,
    company_id: int | None,
    summary_type: str,
    prompt_version: str | None,
    model_name: str | None,
) -> str:
    material = ["ev", str(source_event_id), "co", str(company_id or "global"), summary_type, str(prompt_version or ""), str(model_name or "")]
    return hashlib.sha256("\x1f".join(material).encode("utf-8")).hexdigest()


def _hash(value: str | None) -> str | None:
    text = _clip(value)
    return hashlib.sha256(text.encode("utf-8")).hexdigest() if text else None


def _clip(value: str | None, limit: int = 6000) -> str | None:
    if not value:
        return None
    text = " ".join(str(value).split())
    return text[:limit]


def _clean(value: str | None) -> str:
    return " ".join(str(value or "").split())


def _clamp(value: float | None) -> float | None:
    if value is None:
        return None
    return max(0.0, min(1.0, float(value)))


def _loads(value: str | None) -> dict[str, Any]:
    if not value:
        return {}
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return {}
    return parsed if isinstance(parsed, dict) else {}
