from __future__ import annotations

import html
import json
import re
import sqlite3
import urllib.error
import urllib.request
from html.parser import HTMLParser
from typing import Any

from ..database import NEWS_SUMMARY_SYSTEM_PROMPT, NEWS_SUMMARY_TASK_PROMPT, get_setting, utc_now
from .local_llm import LocalLLMRequestError, llama_cpp_chat_json


NEWS_TOPIC_ENUM = [
    "決算・業績",
    "株主還元",
    "事業・受注",
    "規制・政策",
    "マクロ経済",
    "地政学",
    "市況・需給",
    "アナリスト",
    "その他",
    "不明",
]

SUMMARY_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["topic", "summary", "materiality", "key_points", "risk_notes", "source_basis"],
    "properties": {
        "topic": {"type": "string", "enum": NEWS_TOPIC_ENUM},
        "summary": {"type": "string"},
        "materiality": {"type": "string", "enum": ["positive", "negative", "neutral", "unclear"]},
        "key_points": {"type": "array", "items": {"type": "string"}},
        "risk_notes": {"type": "array", "items": {"type": "string"}},
        "source_basis": {"type": "string", "enum": ["本文", "タイトルのみ", "本文不足"]},
    },
    "additionalProperties": False,
}

MATERIALITY_LABELS = {
    "positive": "ポジティブ",
    "negative": "ネガティブ",
    "neutral": "中立",
    "unclear": "不明",
}


class _TextCollector(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self._chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1
        if tag in {"p", "br", "li", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in {"script", "style", "noscript", "svg"} and self._skip_depth > 0:
            self._skip_depth -= 1
        if tag in {"p", "li", "h1", "h2", "h3"}:
            self._chunks.append("\n")

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._chunks.append(data)

    def text(self) -> str:
        return _squash("\n".join(self._chunks))


def summarize_news_item(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    item: dict[str, Any],
) -> str | None:
    title = str(item.get("title") or "")
    article_text = item.get("content_text") or fetch_article_text(item.get("url"))
    fallback = _fallback_summary(title, article_text)
    provider = get_setting(conn, "news_summary_provider", "llama_cpp") or "llama_cpp"
    if provider != "llama_cpp":
        return fallback

    llm_summary = _llama_cpp_news_summary(conn, company=company, item=item, article_text=article_text)
    return llm_summary or fallback


def summarize_existing_news_for_company(
    conn: sqlite3.Connection,
    security_code: str,
    *,
    limit: int = 20,
    force: bool = False,
) -> list[dict[str, Any]]:
    company = _company(conn, security_code)
    where = "company_id = ?"
    params: list[Any] = [company["id"]]
    if not force:
        where += " AND (summary IS NULL OR summary = '')"
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT *
        FROM news_articles
        WHERE {where}
        ORDER BY COALESCE(information_date, substr(published_at, 1, 10)) DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    now = utc_now()
    updated: list[dict[str, Any]] = []
    for row in rows:
        item = dict(row)
        summary = summarize_news_item(conn, company=company, item=item)
        if not summary:
            continue
        conn.execute(
            """
            UPDATE news_articles
            SET summary = ?, updated_at = ?
            WHERE id = ?
            """,
            (summary, now, item["id"]),
        )
        updated.append({**item, "summary": summary})
    return updated


def _llama_cpp_news_summary(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    item: dict[str, Any],
    article_text: str | None,
) -> str | None:
    timeout = int(get_setting(conn, "news_summary_timeout_seconds", "45") or "45")
    text = _clip(article_text or "", 5000)
    if not text and not item.get("title"):
        return None

    messages = [
        {
            "role": "system",
            "content": get_setting(conn, "prompt_news_summary_system", NEWS_SUMMARY_SYSTEM_PROMPT)
            or NEWS_SUMMARY_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "company": {
                        "security_code": company.get("security_code"),
                        "name": company.get("name"),
                        "sector": company.get("sector"),
                        "industry": company.get("industry"),
                        "business_profile": company.get("business_profile"),
                    },
                    "article": {
                        "title": item.get("title"),
                        "published_at": item.get("published_at"),
                        "provider": item.get("provider"),
                        "url": item.get("url"),
                        "text_excerpt": text,
                    },
                    "task": get_setting(conn, "prompt_news_summary_task", NEWS_SUMMARY_TASK_PROMPT)
                    or NEWS_SUMMARY_TASK_PROMPT,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]
    try:
        parsed = llama_cpp_chat_json(conn, messages=messages, schema=SUMMARY_SCHEMA, temperature=0.1, timeout_seconds=timeout)
    except LocalLLMRequestError:
        return None
    return _format_summary(parsed)


def fetch_article_text(url: Any) -> str | None:
    if not isinstance(url, str) or not url:
        return None
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 stock-visualize-composer/0.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            raw = response.read().decode(charset, errors="replace")
    except (TimeoutError, urllib.error.URLError):
        return None
    return _extract_article_text(raw)


def _extract_article_text(raw_html: str) -> str | None:
    json_ld = _extract_json_ld_article(raw_html)
    if json_ld:
        return _clip(json_ld, 6000)
    collector = _TextCollector()
    collector.feed(raw_html)
    text = collector.text()
    if not text:
        return None
    return _clip(text, 6000)


def _extract_json_ld_article(raw_html: str) -> str | None:
    for match in re.finditer(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", raw_html, re.DOTALL | re.IGNORECASE):
        body = html.unescape(match.group(1)).strip()
        try:
            parsed = json.loads(body)
        except json.JSONDecodeError:
            continue
        for node in _json_nodes(parsed):
            if not isinstance(node, dict):
                continue
            article_body = node.get("articleBody") or node.get("description")
            if article_body:
                return _squash(str(article_body))
    return None


def _json_nodes(value: Any) -> list[Any]:
    if isinstance(value, list):
        return [node for item in value for node in _json_nodes(item)]
    if isinstance(value, dict):
        nodes = [value]
        graph = value.get("@graph")
        if graph:
            nodes.extend(_json_nodes(graph))
        return nodes
    return []


def _format_summary(parsed: dict[str, Any]) -> str:
    topic = _squash(str(parsed.get("topic") or "不明"))
    summary = _squash(str(parsed.get("summary") or ""))
    materiality = _squash(str(parsed.get("materiality") or "unclear"))
    points = [_squash(str(item)) for item in parsed.get("key_points") or [] if str(item).strip()]
    risks = [_squash(str(item)) for item in parsed.get("risk_notes") or [] if str(item).strip()]
    source_basis = _squash(str(parsed.get("source_basis") or "本文不足"))
    parts = []
    if topic:
        parts.append(f"分類: {topic}")
    if summary:
        parts.append(f"要約: {summary}")
    if points:
        parts.append("要点: " + " / ".join(points[:3]))
    if risks:
        parts.append("注意: " + " / ".join(risks[:2]))
    if materiality:
        parts.append(f"材料性: {MATERIALITY_LABELS.get(materiality, materiality)}")
    if source_basis:
        parts.append(f"根拠: {source_basis}")
    return _clip(" ".join(parts), 640)


def _fallback_summary(title: str, article_text: str | None) -> str | None:
    if article_text:
        return _clip(f"分類: 不明 要約: {_squash(article_text)} 材料性: 不明 根拠: 本文不足", 520)
    return _clip(f"分類: 不明 要約: タイトルのみ確認: {title} 材料性: 不明 根拠: タイトルのみ", 360) if title else None


def _company(conn: sqlite3.Connection, security_code: str) -> dict[str, Any]:
    row = conn.execute(
        "SELECT * FROM companies WHERE security_code = ? AND is_active = 1",
        (security_code,),
    ).fetchone()
    if row is None:
        raise ValueError(f"Company not found: {security_code}")
    return dict(row)


def _clip(value: str, limit: int) -> str:
    text = _squash(value)
    if len(text) <= limit:
        return text
    return text[: limit - 3] + "..."


def _squash(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()
