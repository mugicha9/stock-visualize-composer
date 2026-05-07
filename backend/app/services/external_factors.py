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

from ..database import row_to_dict, utc_now
from .information_dates import infer_information_date


class ExternalFactorSourceError(RuntimeError):
    pass


@dataclass(frozen=True)
class FeedSource:
    source: str
    provider: str
    category: str
    url: str


FEEDS = [
    FeedSource(
        source="nhk_economy_rss",
        provider="NHK",
        category="economy",
        url="https://news.web.nhk/n-data/conf/na/rss/cat5.xml",
    ),
    FeedSource(
        source="nhk_politics_rss",
        provider="NHK",
        category="politics_policy",
        url="https://news.web.nhk/n-data/conf/na/rss/cat4.xml",
    ),
    FeedSource(
        source="nhk_international_rss",
        provider="NHK",
        category="geopolitics",
        url="https://news.web.nhk/n-data/conf/na/rss/cat6.xml",
    ),
    FeedSource(
        source="meti_release_atom",
        provider="経済産業省",
        category="policy",
        url="https://www.meti.go.jp/ml_index_release_atom.xml",
    ),
    FeedSource(
        source="meti_statistics_rdf",
        provider="経済産業省",
        category="macro_statistics",
        url="https://www.meti.go.jp/statistics/st_news.xml",
    ),
    FeedSource(
        source="boj_whatsnew_rdf",
        provider="日本銀行",
        category="monetary_policy",
        url="https://www.boj.or.jp/whatsnew.rdf",
    ),
    FeedSource(
        source="cao_release_rdf",
        provider="内閣府",
        category="macro_policy",
        url="https://www.cao.go.jp/rss/news.rdf",
    ),
    FeedSource(
        source="fsa_news_rss",
        provider="金融庁",
        category="financial_regulation",
        url="https://www.fsa.go.jp/news_rss2.xml",
    ),
]

BASE_EXTERNAL_KEYWORDS = [
    "金利",
    "為替",
    "円相場",
    "ドル",
    "原油",
    "エネルギー",
    "関税",
    "輸出",
    "輸入",
    "サプライチェーン",
    "地政学",
    "規制",
    "税制",
    "減税",
    "補助金",
    "政策",
    "経済安全保障",
    "中国",
    "米国",
    "アメリカ",
    "欧州",
    "中東",
    "イラン",
    "台湾",
    "紅海",
    "ウクライナ",
    "ロシア",
    "金融政策",
    "日銀",
    "金融庁",
    "内閣府",
    "経済安全保障",
    "重要物資",
    "半導体",
    "生成AI",
]

INDUSTRY_KEYWORDS: dict[str, list[str]] = {
    "自動車": ["自動車", "EV", "電気自動車", "車載", "部品", "輸送用機器", "ガソリン"],
    "輸送用機器": ["自動車", "EV", "電気自動車", "車載", "部品", "輸送用機器", "ガソリン"],
    "半導体": ["半導体", "AI", "生成AI", "データセンター", "電子部品", "パワー半導体"],
    "電気機器": ["半導体", "AI", "生成AI", "データセンター", "電子部品", "電機"],
    "銀行": ["銀行", "金利", "日銀", "融資", "資金需要", "不良債権"],
    "銀行業": ["銀行", "金利", "日銀", "融資", "資金需要", "不良債権"],
    "保険": ["保険", "金利", "災害", "再保険", "損害"],
    "情報・通信": ["通信", "AI", "データセンター", "クラウド", "規制", "サイバー"],
    "情報・通信業": ["通信", "AI", "データセンター", "クラウド", "規制", "サイバー"],
    "医薬品": ["医薬品", "薬価", "承認", "治験", "医療", "バイオ"],
    "化学": ["化学", "素材", "半導体材料", "原料", "石化", "脱炭素"],
    "機械": ["機械", "設備投資", "工作機械", "ロボット", "工場", "製造業"],
    "精密機器": ["精密機器", "医療機器", "半導体", "光学", "設備投資"],
    "商社": ["資源", "原油", "LNG", "石炭", "穀物", "投資", "貿易"],
    "卸売業": ["資源", "原油", "LNG", "石炭", "穀物", "投資", "貿易"],
    "食品": ["食品", "原材料", "小麦", "価格転嫁", "消費", "円安"],
    "食料品": ["食品", "原材料", "小麦", "価格転嫁", "消費", "円安"],
    "小売": ["小売", "消費", "物価", "賃上げ", "インバウンド"],
    "不動産": ["不動産", "住宅", "金利", "マンション", "地価"],
    "空運": ["航空", "燃油", "インバウンド", "為替", "旅行"],
    "海運": ["海運", "運賃", "港湾", "紅海", "燃料"],
    "電力": ["電力", "原発", "燃料", "LNG", "再エネ", "電気料金"],
}


def update_external_factors_for_company(conn: sqlite3.Connection, security_code: str, limit: int = 30) -> list[dict[str, Any]]:
    company = _company(conn, security_code)
    keywords = _keywords_for_company(company)
    items: list[dict[str, Any]] = []
    failed_sources: list[str] = []
    for source in FEEDS:
        try:
            source_items = _fetch_feed(source)
        except ExternalFactorSourceError:
            failed_sources.append(source.source)
            continue
        for item in source_items:
            score, matched = _score_item(item, keywords)
            if score < 0.18:
                continue
            items.append({**item, "relevance_score": score, "matched_keywords": matched})
    if failed_sources and len(failed_sources) == len(FEEDS):
        raise ExternalFactorSourceError("All external factor feeds failed")

    deduped = _dedupe(items)
    deduped.sort(key=lambda item: (item.get("published_at") or "", item.get("relevance_score") or 0), reverse=True)
    now = utc_now()
    for item in deduped[:limit]:
        conn.execute(
            """
            INSERT INTO external_factors
                (company_id, category, title, published_at, information_date, source, provider, url, summary,
                 relevance_score, matched_keywords, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id, source, url) DO UPDATE SET
                category = excluded.category,
                title = excluded.title,
                published_at = excluded.published_at,
                information_date = excluded.information_date,
                provider = excluded.provider,
                summary = excluded.summary,
                relevance_score = excluded.relevance_score,
                matched_keywords = excluded.matched_keywords,
                updated_at = excluded.updated_at
            """,
            (
                company["id"],
                item["category"],
                item["title"],
                item["published_at"],
                infer_information_date(
                    title=item["title"],
                    published_at=item["published_at"],
                    url=item["url"],
                ),
                item["source"],
                item["provider"],
                item["url"],
                item["summary"],
                item["relevance_score"],
                ", ".join(item["matched_keywords"]),
                now,
                now,
            ),
        )
    return list_external_factors_for_company(conn, security_code, limit=limit)


def list_external_factors_for_company(conn: sqlite3.Connection, security_code: str, limit: int = 20) -> list[dict[str, Any]]:
    company = _company(conn, security_code)
    rows = conn.execute(
        """
        SELECT *
        FROM external_factors
        WHERE company_id = ?
        ORDER BY COALESCE(information_date, substr(published_at, 1, 10)) DESC, relevance_score DESC, id DESC
        LIMIT ?
        """,
        (company["id"], limit),
    ).fetchall()
    return [dict(row) for row in rows]


def _company(conn: sqlite3.Connection, security_code: str) -> dict[str, Any]:
    company = row_to_dict(
        conn.execute(
            "SELECT * FROM companies WHERE security_code = ? AND is_active = 1",
            (security_code,),
        ).fetchone()
    )
    if company is None:
        raise ValueError(f"Company not found: {security_code}")
    return company


def _fetch_feed(source: FeedSource) -> list[dict[str, Any]]:
    text = _request_text(source.url)
    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        raise ExternalFactorSourceError(f"{source.url} parse failed: {exc}") from exc

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
        href = link.attrib.get("href") if link is not None else None
        items.append(
            _item(
                source=source,
                title=_text(entry.find("atom:title", ns)),
                url=href,
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
    ns = {
        "rss": "http://purl.org/rss/1.0/",
        "dc": "http://purl.org/dc/elements/1.1/",
    }
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


def _request_text(url: str, timeout_seconds: int = 30) -> str:
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
        raise ExternalFactorSourceError(f"{url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise ExternalFactorSourceError(f"{url} request failed: {exc}") from exc


def _keywords_for_company(company: dict[str, Any]) -> list[str]:
    keywords = [str(company.get("name") or ""), str(company.get("sector") or ""), str(company.get("industry") or "")]
    for value in (company.get("sector"), company.get("industry")):
        if not value:
            continue
        for key, mapped in INDUSTRY_KEYWORDS.items():
            if key in str(value):
                keywords.extend(mapped)
    keywords.extend(BASE_EXTERNAL_KEYWORDS)
    return sorted({keyword.strip() for keyword in keywords if keyword and keyword.strip()}, key=len, reverse=True)


def _score_item(item: dict[str, Any], keywords: list[str]) -> tuple[float, list[str]]:
    text = f"{item.get('title') or ''} {item.get('summary') or ''}"
    matched = [keyword for keyword in keywords if keyword in text]
    if not matched:
        return 0.0, []
    score = min(1.0, 0.12 + 0.08 * len(matched))
    if item.get("category") in {"policy", "politics_policy", "geopolitics", "monetary_policy", "macro_policy", "financial_regulation"}:
        score += 0.08
    if any(keyword in matched for keyword in BASE_EXTERNAL_KEYWORDS):
        score += 0.1
    return min(1.0, round(score, 2)), matched[:8]


def _dedupe(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str]] = set()
    result: list[dict[str, Any]] = []
    for item in items:
        key = (str(item.get("source") or ""), str(item.get("url") or item.get("title") or ""))
        if key in seen:
            continue
        seen.add(key)
        result.append(item)
    return result


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
