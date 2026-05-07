from __future__ import annotations

import re
import urllib.error
import urllib.request
from pathlib import Path
from tempfile import NamedTemporaryFile

from pypdf import PdfReader

from ..database import db_session, init_db, utc_now


JPX400_CONSTITUENTS_PDF_URL = (
    "https://www.jpx.co.jp/markets/indices/jpx-nikkei400/"
    "tvdivq00000031dd-att/400_j.pdf"
)


def fetch_jpx400_companies() -> tuple[list[tuple[str, str, str, None, None]], str | None]:
    request = urllib.request.Request(
        JPX400_CONSTITUENTS_PDF_URL,
        headers={
            "User-Agent": "Mozilla/5.0 stock-visualize-composer/0.1",
            "Accept": "application/pdf,*/*",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            content = response.read()
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to download JPX400 constituents PDF: {exc}") from exc

    with NamedTemporaryFile(suffix=".pdf", delete=False) as tmp:
        tmp.write(content)
        tmp_path = Path(tmp.name)
    try:
        text = "\n".join(page.extract_text() or "" for page in PdfReader(str(tmp_path)).pages)
    finally:
        tmp_path.unlink(missing_ok=True)

    as_of_match = re.search(r"構成銘柄一覧\s*[（(](\d{4}年\d{1,2}月\d{1,2}日時点)", text)
    as_of = as_of_match.group(1) if as_of_match else None
    companies: list[tuple[str, str, str, None, None]] = []
    for line in text.splitlines():
        match = re.match(r"^([0-9]{4}|[0-9]{3}[A-Z])\s+(プライム|スタンダード|グロース)\s+(.+?)\s+\d+$", line.strip())
        if not match:
            continue
        security_code, market, name = match.groups()
        companies.append((security_code, name, market, None, None))
    if len(companies) < 300:
        raise RuntimeError(f"Parsed only {len(companies)} JPX400 constituents from JPX PDF")
    return companies, as_of


def main() -> None:
    init_db()
    now = utc_now()
    companies, as_of = fetch_jpx400_companies()
    current_codes = [security_code for security_code, *_ in companies]
    with db_session() as conn:
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES ('watchlist_default', 'JPX400', ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (now,),
        )
        placeholders = ",".join("?" for _ in current_codes)
        conn.execute(
            f"""
            UPDATE watchlists
            SET is_active = 0, updated_at = ?
            WHERE list_name = 'JPX400'
              AND company_id IN (
                  SELECT id FROM companies WHERE security_code NOT IN ({placeholders})
              )
            """,
            (now, *current_codes),
        )
        for priority, (security_code, name, market, sector, industry) in enumerate(reversed(companies), start=1):
            conn.execute(
                """
                INSERT INTO companies
                    (security_code, name, market, sector, industry, fiscal_year_end, is_active, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, '03-31', 1, ?, ?)
                ON CONFLICT(security_code) DO UPDATE SET
                    name = excluded.name,
                    market = excluded.market,
                    sector = excluded.sector,
                    industry = excluded.industry,
                    fiscal_year_end = excluded.fiscal_year_end,
                    is_active = 1,
                    updated_at = excluded.updated_at
                """,
                (security_code, name, market, sector, industry, now, now),
            )
            company = conn.execute(
                "SELECT id FROM companies WHERE security_code = ?",
                (security_code,),
            ).fetchone()
            conn.execute(
                """
                INSERT INTO watchlists
                    (company_id, list_name, memo, priority, is_active, created_at, updated_at)
                VALUES (?, 'JPX400', ?, ?, 1, ?, ?)
                ON CONFLICT(company_id, list_name) DO UPDATE SET
                    memo = excluded.memo,
                    priority = excluded.priority,
                    is_active = 1,
                    updated_at = excluded.updated_at
                """,
                (
                    company["id"],
                    f"JPX400 constituents from JPX PDF"
                    + (f" ({as_of})" if as_of else ""),
                    priority,
                    now,
                    now,
                ),
            )
    print(f"Seeded {len(companies)} JPX400 watchlist companies" + (f" ({as_of})" if as_of else ""))


if __name__ == "__main__":
    main()
