from __future__ import annotations

import re
import sqlite3
from datetime import date, datetime, timedelta
from typing import Any


INFORMATION_DATE_TABLES = ("news_articles", "disclosures", "external_factors", "global_news")


def ensure_information_date_columns(conn: sqlite3.Connection) -> None:
    for table in INFORMATION_DATE_TABLES:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if "information_date" not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN information_date TEXT")
        has_company_id = "company_id" in columns
        if has_company_id:
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table}_company_information_date
                ON {table}(company_id, information_date)
                """
            )
        else:
            conn.execute(
                f"""
                CREATE INDEX IF NOT EXISTS idx_{table}_information_date
                ON {table}(information_date)
                """
            )


def refresh_information_dates(conn: sqlite3.Connection) -> dict[str, int]:
    ensure_information_date_columns(conn)
    updated: dict[str, int] = {}
    for table in INFORMATION_DATE_TABLES:
        rows = conn.execute(
            f"""
            SELECT id, title, published_at, url, created_at
            FROM {table}
            WHERE information_date IS NULL OR information_date = ''
            """
        ).fetchall()
        count = 0
        for row in rows:
            information_date = infer_information_date(
                title=row["title"],
                published_at=row["published_at"],
                url=row["url"],
                created_at=row["created_at"],
            )
            if information_date is None:
                continue
            conn.execute(f"UPDATE {table} SET information_date = ? WHERE id = ?", (information_date, row["id"]))
            count += 1
        updated[table] = count
    return updated


def infer_information_date(
    *,
    title: str | None = None,
    published_at: str | None = None,
    url: str | None = None,
    created_at: str | None = None,
) -> str | None:
    return (
        _date_from_any(published_at)
        or _date_from_url(url)
        or _date_from_title(title, _base_date(created_at))
    )


def _date_from_any(value: str | None) -> str | None:
    if not value:
        return None
    text = value.strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).date().isoformat()
    except ValueError:
        pass

    for pattern in (
        r"(20\d{2})[-/年](\d{1,2})[-/月](\d{1,2})",
        r"(20\d{2})(\d{2})(\d{2})",
    ):
        match = re.search(pattern, text)
        if match:
            return _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))
    return None


def _date_from_url(url: str | None) -> str | None:
    if not url:
        return None
    match = re.search(r"(20\d{2})(\d{2})(\d{2})", url)
    if not match:
        return None
    return _safe_date(int(match.group(1)), int(match.group(2)), int(match.group(3)))


def _date_from_title(title: str | None, base: date | None) -> str | None:
    if not title:
        return None
    base_date = base or date.today()
    explicit = _date_from_any(title)
    if explicit:
        return explicit

    match = re.search(r"(\d{1,2})[月/](\d{1,2})日?", title)
    if not match:
        return None
    month = int(match.group(1))
    day = int(match.group(2))
    year = base_date.year
    parsed = _date_object(year, month, day)
    if parsed is None:
        return None
    if parsed > base_date + timedelta(days=7):
        parsed = _date_object(year - 1, month, day)
    return parsed.isoformat() if parsed else None


def _base_date(created_at: str | None) -> date | None:
    return _date_object_from_iso(created_at)


def _date_object_from_iso(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _safe_date(year: int, month: int, day: int) -> str | None:
    parsed = _date_object(year, month, day)
    return parsed.isoformat() if parsed else None


def _date_object(year: int, month: int, day: int) -> date | None:
    try:
        return date(year, month, day)
    except ValueError:
        return None
