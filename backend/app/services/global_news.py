from __future__ import annotations

import html
import re
import sqlite3
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from ..database import utc_now
from .content_summaries import fetch_article_text
from .information_dates import infer_information_date
from .news_policy import canonical_news_url


class GlobalNewsSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeedSource:
    source: str
    provider: str
    category: str
    url: str


FEEDS = [
    FeedSource("nhk_economy_rss", "NHK", "economy", "https://news.web.nhk/n-data/conf/na/rss/cat5.xml"),
    FeedSource("nhk_politics_rss", "NHK", "politics_policy", "https://news.web.nhk/n-data/conf/na/rss/cat4.xml"),
    FeedSource("nhk_international_rss", "NHK", "geopolitics", "https://news.web.nhk/n-data/conf/na/rss/cat6.xml"),
    FeedSource("meti_release_atom", "経済産業省", "policy", "https://www.meti.go.jp/ml_index_release_atom.xml"),
    FeedSource("meti_statistics_rdf", "経済産業省", "macro_statistics", "https://www.meti.go.jp/statistics/st_news.xml"),
    FeedSource("boj_whatsnew_rdf", "日本銀行", "monetary_policy", "https://www.boj.or.jp/whatsnew.rdf"),
    FeedSource("cao_release_rdf", "内閣府", "macro_policy", "https://www.cao.go.jp/rss/news.rdf"),
    FeedSource("fsa_news_rss", "金融庁", "financial_regulation", "https://www.fsa.go.jp/news_rss2.xml"),
]


GLOBAL_KEYWORDS = [
    "金融政策",
    "日銀",
    "金利",
    "為替",
    "円安",
    "円高",
    "物価",
    "景気",
    "GDP",
    "雇用",
    "消費",
    "関税",
    "輸出規制",
    "制裁",
    "経済安全保障",
    "重要物資",
    "半導体",
    "生成AI",
    "データセンター",
    "サイバー",
    "原油",
    "LNG",
    "ナフサ",
    "資源",
    "サプライチェーン",
    "中国",
    "米国",
    "アメリカ",
    "欧州",
    "中東",
    "台湾",
    "紅海",
    "ロシア",
    "ウクライナ",
    "地政学",
    "金融庁",
    "規制",
    "行政処分",
    "補助金",
]


def update_global_news(conn: sqlite3.Connection, *, limit_per_source: int = 40, fetch_body: bool = False) -> dict[str, Any]:
    now = utc_now()
    inserted_or_updated = 0
    skipped = 0
    errors: dict[str, str] = {}
    for source in FEEDS:
        try:
            items = _fetch_feed(source)
        except GlobalNewsSourceError as exc:
            errors[source.source] = str(exc)
            continue
        for item in items[:limit_per_source]:
            if not _is_material_global_news(item):
                skipped += 1
                continue
            url = canonical_news_url(item.get("url"))
            content_text = item.get("summary")
            if fetch_body:
                content_text = fetch_article_text(url) or content_text
            conn.execute(
                """
                INSERT INTO global_news
                    (category, title, published_at, information_date, source, provider, url, content_text,
                     summary, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(source, url) DO UPDATE SET
                    category = excluded.category,
                    title = excluded.title,
                    published_at = excluded.published_at,
                    information_date = excluded.information_date,
                    provider = excluded.provider,
                    content_text = COALESCE(excluded.content_text, global_news.content_text),
                    summary = COALESCE(global_news.summary, excluded.summary),
                    updated_at = excluded.updated_at
                """,
                (
                    item["category"],
                    item["title"],
                    item["published_at"],
                    infer_information_date(title=item["title"], published_at=item["published_at"], url=url),
                    item["source"],
                    item["provider"],
                    url,
                    content_text,
                    item.get("summary"),
                    now,
                    now,
                ),
            )
            inserted_or_updated += 1
    if errors and inserted_or_updated == 0:
        raise GlobalNewsSourceError("; ".join(errors.values()))
    return {"count": inserted_or_updated, "skipped": skipped, "errors": errors}


def list_global_news(conn: sqlite3.Connection, *, limit: int = 50, as_of: str | None = None) -> list[dict[str, Any]]:
    params: list[Any] = []
    date_expr = "COALESCE(information_date, substr(published_at, 1, 10))"
    date_filter = ""
    if as_of:
        date_filter = f"WHERE {date_expr} IS NOT NULL AND {date_expr} <= ?"
        params.append(as_of)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT id, category, title, published_at, {date_expr} AS information_date,
               source, provider, url, content_text, summary
        FROM global_news
        {date_filter}
        ORDER BY {date_expr} DESC, id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def _fetch_feed(source: FeedSource) -> list[dict[str, Any]]:
    text = _request_text(source.url)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise GlobalNewsSourceError(f"{source.url} parse failed: {exc}") from exc

    if root.tag.endswith("feed"):
        return _parse_atom(root, source)
    if root.tag.endswith("rss"):
        return _parse_rss(root, source)
    if root.tag.endswith("RDF"):
        return _parse_rdf(root, source)
    return []


def _parse_atom(root: ET.Element, source: FeedSource) -> list[dict[str, Any]]:
    ns = {"atom": "http://www.w3.org/2005/Atom"}
    items = []
    for entry in root.findall("atom:entry", ns):
        link = entry.find("atom:link", ns)
        items.append(
            _item(
                source=source,
                title=_text(entry.find("atom:title", ns)),
                url=link.attrib.get("href") if link is not None else None,
                summary=_text(entry.find("atom:summary", ns)),
                published_at=_parse_date(_text(entry.find("atom:updated", ns))),
            )
        )
    return [item for item in items if item["title"] and item["url"]]


def _parse_rss(root: ET.Element, source: FeedSource) -> list[dict[str, Any]]:
    items = []
    for entry in root.findall("./channel/item"):
        items.append(
            _item(
                source=source,
                title=_text(entry.find("title")),
                url=_text(entry.find("link")),
                summary=_text(entry.find("description")),
                published_at=_parse_date(_text(entry.find("pubDate"))),
            )
        )
    return [item for item in items if item["title"] and item["url"]]


def _parse_rdf(root: ET.Element, source: FeedSource) -> list[dict[str, Any]]:
    ns = {"rss": "http://purl.org/rss/1.0/", "dc": "http://purl.org/dc/elements/1.1/"}
    items = []
    for entry in root.findall("rss:item", ns):
        items.append(
            _item(
                source=source,
                title=_text(entry.find("rss:title", ns)),
                url=_text(entry.find("rss:link", ns)),
                summary=_text(entry.find("rss:description", ns)),
                published_at=_parse_date(_text(entry.find("dc:date", ns))),
            )
        )
    return [item for item in items if item["title"] and item["url"]]


def _item(
    *,
    source: FeedSource,
    title: str | None,
    url: str | None,
    summary: str | None,
    published_at: str | None,
) -> dict[str, Any]:
    return {
        "category": source.category,
        "title": _squash(title),
        "published_at": published_at,
        "source": source.source,
        "provider": source.provider,
        "url": url,
        "summary": _squash(summary),
    }


def _is_material_global_news(item: dict[str, Any]) -> bool:
    text = f"{item.get('title') or ''} {item.get('summary') or ''}"
    if item.get("category") in {"geopolitics", "monetary_policy", "financial_regulation"}:
        return True
    return any(keyword in text for keyword in GLOBAL_KEYWORDS)


def _request_text(url: str, timeout_seconds: int = 20) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 stock-visualize-composer/0.1",
            "Accept": "application/rss+xml,application/atom+xml,application/xml,text/xml,*/*",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise GlobalNewsSourceError(f"{url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise GlobalNewsSourceError(f"{url} request failed: {exc}") from exc


def _parse_date(value: str | None) -> str | None:
    if not value:
        return None
    try:
        if "," in value:
            parsed = parsedate_to_datetime(value)
        else:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.isoformat()


def _text(element: ET.Element | None) -> str | None:
    if element is None or element.text is None:
        return None
    return element.text


def _squash(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()
