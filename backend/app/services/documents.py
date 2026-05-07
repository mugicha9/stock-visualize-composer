from __future__ import annotations

import hashlib
import re
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from pypdf import PdfReader

from ..config import DATA_DIR
from ..database import get_setting, utc_now


DOCUMENTS_DIR = DATA_DIR / "documents" / "disclosures"
TEXT_DIR = DATA_DIR / "extracted_text" / "disclosures"


class DocumentExtractionError(RuntimeError):
    pass


def process_disclosure_pdf(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    disclosure: dict[str, Any],
) -> dict[str, Any]:
    url = str(disclosure.get("url") or "")
    if not url.lower().endswith(".pdf"):
        return {"status": "skipped", "reason": "not_pdf"}

    pdf_path = _download_pdf(url, company_code=str(company.get("security_code") or "unknown"))
    max_pages = int(get_setting(conn, "disclosure_pdf_max_pages", "8") or "8")
    extracted = _extract_pdf_text(pdf_path, max_pages=max_pages)
    status = "extracted" if len(extracted) >= 80 else "needs_ocr"
    text_path: Path | None = None
    if extracted:
        text_path = TEXT_DIR / str(company.get("security_code") or "unknown") / (pdf_path.stem + ".txt")
        text_path.parent.mkdir(parents=True, exist_ok=True)
        text_path.write_text(extracted, encoding="utf-8")

    now = utc_now()
    existing = conn.execute("SELECT id FROM documents WHERE url = ? AND company_id = ?", (url, company.get("id"))).fetchone()
    if existing:
        conn.execute(
            """
            UPDATE documents
            SET source = ?, document_type = ?, title = ?, published_at = ?, local_path = ?, raw_text_path = ?,
                extracted_text_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                disclosure.get("source") or "tdnet",
                disclosure.get("document_type") or "disclosure_pdf",
                disclosure.get("title") or pdf_path.name,
                disclosure.get("published_at"),
                str(pdf_path),
                str(text_path) if text_path else None,
                status,
                now,
                existing["id"],
            ),
        )
    else:
        conn.execute(
            """
            INSERT INTO documents
                (company_id, source, document_type, title, published_at, url, local_path, raw_text_path,
                 extracted_text_status, metadata_json, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                company.get("id"),
                disclosure.get("source") or "tdnet",
                disclosure.get("document_type") or "disclosure_pdf",
                disclosure.get("title") or pdf_path.name,
                disclosure.get("published_at"),
                url,
                str(pdf_path),
                str(text_path) if text_path else None,
                status,
                None,
                now,
                now,
            ),
        )
    summary = _summary_from_text(extracted) if extracted else None
    if disclosure.get("id"):
        conn.execute(
            """
            UPDATE disclosures
            SET local_path = ?,
                summary = CASE
                    WHEN ? IS NOT NULL AND (summary IS NULL OR summary = '' OR summary = 'TDnet PDF') THEN ?
                    ELSE summary
                END,
                updated_at = ?
            WHERE id = ?
            """,
            (str(pdf_path), summary, summary, now, disclosure["id"]),
        )
    return {
        "status": status,
        "local_path": str(pdf_path),
        "raw_text_path": str(text_path) if text_path else None,
        "summary": summary,
    }


def _download_pdf(url: str, *, company_code: str) -> Path:
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:20]
    target = DOCUMENTS_DIR / company_code / f"{digest}.pdf"
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 stock-visualize-composer/0.1",
            "Accept": "application/pdf,*/*",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            target.write_bytes(response.read())
    except (urllib.error.HTTPError, urllib.error.URLError) as exc:
        raise DocumentExtractionError(f"{url} PDF download failed: {exc}") from exc
    return target


def _extract_pdf_text(path: Path, *, max_pages: int) -> str:
    try:
        reader = PdfReader(str(path))
        chunks = []
        for page in list(reader.pages)[:max_pages]:
            chunks.append(page.extract_text() or "")
    except Exception as exc:  # pypdf can raise parser-specific exceptions.
        raise DocumentExtractionError(f"{path} PDF text extraction failed: {exc}") from exc
    return _squash("\n".join(chunks))


def _summary_from_text(text: str, *, limit: int = 900) -> str | None:
    normalized = _squash(text)
    if not normalized:
        return None
    return normalized[:limit] + ("..." if len(normalized) > limit else "")


def _squash(value: str | None) -> str:
    return re.sub(r"\s+", " ", value or "").strip()
