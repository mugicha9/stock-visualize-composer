from __future__ import annotations

import html
import json
import re
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time, timedelta, timezone
from html.parser import HTMLParser
from typing import Any

from ..database import get_setting, row_to_dict, utc_now
from .company_news_profile import get_company_news_profile, score_company_news_candidate
from .content_summaries import fetch_article_text, summarize_news_item
from .documents import DocumentExtractionError, process_disclosure_pdf
from .information_dates import infer_information_date
from .news_policy import canonical_news_url, decide_company_news
from .source_events import list_company_events, record_event_triage, upsert_event_summary, upsert_source_event


JST = timezone(timedelta(hours=9))
YAHOO_FINANCE_BASE = "https://finance.yahoo.co.jp"


class CompanySourceError(RuntimeError):
    pass


class _LinkCollector(HTMLParser):
    def __init__(self, href_predicate: re.Pattern[str]) -> None:
        super().__init__(convert_charrefs=True)
        self.href_predicate = href_predicate
        self._active_href: str | None = None
        self._buffer: list[str] = []
        self.links: list[tuple[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag != "a":
            return
        href = dict(attrs).get("href")
        if href and self.href_predicate.search(href):
            self._active_href = href
            self._buffer = []

    def handle_data(self, data: str) -> None:
        if self._active_href:
            self._buffer.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag != "a" or not self._active_href:
            return
        text = _squash("".join(self._buffer))
        if text:
            self.links.append((self._active_href, text))
        self._active_href = None
        self._buffer = []


class YahooJapanFinanceSource:
    name = "yahoo_finance_japan"

    def fetch_financial_snapshot(self, security_code: str) -> dict[str, Any]:
        url = f"{YAHOO_FINANCE_BASE}/quote/{security_code}.T"
        quote_fallback = _fetch_quote_fallback(security_code)
        try:
            text = _jsonish(_request_text(url))
        except CompanySourceError:
            if quote_fallback.get("metrics"):
                today = date.today().isoformat()
                return {
                    "source": "yahoo_finance_quote",
                    "as_of": today,
                    "fiscal_period": None,
                    "next_earnings_date": None,
                    "summary": None,
                    "metrics": quote_fallback["metrics"],
                    "url": url,
                    "company_update": {
                        "name": quote_fallback.get("name"),
                        "market": quote_fallback.get("market"),
                        "industry": None,
                    },
                }
            raise
        metrics = {
            key: metric
            for key, metric in {
                "market_cap": _extract_metric(text, "totalPrice"),
                "shares_issued": _extract_metric(text, "sharesIssued"),
                "dividend_yield": _extract_metric(text, "shareDividendYield"),
                "dividend_per_share": _extract_metric(text, "dps"),
                "per": _extract_metric(text, "per"),
                "pbr": _extract_metric(text, "pbr"),
                "eps": _extract_metric(text, "eps"),
                "bps": _extract_metric(text, "bps"),
                "roe": _extract_metric(text, "roe"),
                "equity_ratio": _extract_metric(text, "equityRatio"),
            }.items()
            if metric
        }
        for key, metric in quote_fallback.get("metrics", {}).items():
            metrics.setdefault(key, metric)
        summary = _extract_press_release_summary(text) or _extract_performance_summary(text)
        next_earnings_date = _extract_next_earnings_date(text)
        company_name = _extract_company_name(text) or quote_fallback.get("name")
        market = _extract_first_prop(text, "marketName") or quote_fallback.get("market")
        industry = _extract_first_prop(text, "industryName") or _extract_industry_name(text)
        as_of = _latest_metric_date(metrics) or date.today().isoformat()
        return {
            "source": self.name,
            "as_of": as_of,
            "fiscal_period": _extract_fiscal_period(text),
            "next_earnings_date": next_earnings_date,
            "summary": summary,
            "metrics": metrics,
            "url": url,
            "company_update": {
                "name": company_name,
                "market": market,
                "industry": industry,
            },
        }

    def fetch_news(self, security_code: str, limit: int = 20) -> list[dict[str, Any]]:
        url = f"{YAHOO_FINANCE_BASE}/quote/{security_code}.T/news"
        parser = _LinkCollector(re.compile(r"/news/detail/"))
        parser.feed(_request_text(url))
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for href, raw_text in parser.links:
            full_url = href if href.startswith("http") else f"{YAHOO_FINANCE_BASE}{href}"
            if full_url in seen:
                continue
            seen.add(full_url)
            parsed = _split_news_text(raw_text)
            if not parsed["title"]:
                continue
            items.append(
                {
                    "title": parsed["title"],
                    "published_at": parsed["published_at"],
                    "information_date": infer_information_date(
                        title=parsed["title"],
                        published_at=parsed["published_at"],
                        url=full_url,
                    ),
                    "provider": parsed["provider"],
                    "source": "yahoo_finance_news",
                    "url": full_url,
                    "summary": None,
                }
            )
            if len(items) >= limit:
                break
        return items

    def fetch_disclosures(self, security_code: str, limit: int = 40) -> list[dict[str, Any]]:
        url = f"{YAHOO_FINANCE_BASE}/quote/{security_code}.T/disclosure"
        parser = _LinkCollector(re.compile(r"/disclosure/.*\.pdf"))
        parser.feed(_request_text(url))
        seen: set[str] = set()
        items: list[dict[str, Any]] = []
        for href, raw_text in parser.links:
            full_url = href if href.startswith("http") else f"{YAHOO_FINANCE_BASE}{href}"
            if full_url in seen:
                continue
            seen.add(full_url)
            parsed = _split_disclosure_text(raw_text)
            if not parsed["title"]:
                continue
            items.append(
                {
                    "title": parsed["title"],
                    "document_type": _classify_disclosure(parsed["title"]),
                    "published_at": parsed["published_at"],
                    "information_date": infer_information_date(
                        title=parsed["title"],
                        published_at=parsed["published_at"],
                        url=full_url,
                    ),
                    "source": "tdnet_via_yahoo_finance",
                    "url": full_url,
                    "summary": parsed["summary"],
                    "importance_score": _importance_score(parsed["title"]),
                }
            )
            if len(items) >= limit:
                break
        return items


def update_financials_for_company(conn: sqlite3.Connection, security_code: str) -> dict[str, Any]:
    company = _company(conn, security_code)
    snapshot = YahooJapanFinanceSource().fetch_financial_snapshot(security_code)
    _update_company_from_snapshot(conn, int(company["id"]), company, snapshot.get("company_update") or {})
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO company_financials
            (company_id, source, as_of, fiscal_period, next_earnings_date, summary,
             metrics_json, url, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_id, source, as_of) DO UPDATE SET
            fiscal_period = excluded.fiscal_period,
            next_earnings_date = excluded.next_earnings_date,
            summary = excluded.summary,
            metrics_json = excluded.metrics_json,
            url = excluded.url,
            updated_at = excluded.updated_at
        """,
        (
            company["id"],
            snapshot["source"],
            snapshot["as_of"],
            snapshot["fiscal_period"],
            snapshot["next_earnings_date"],
            snapshot["summary"],
            json.dumps(snapshot["metrics"], ensure_ascii=False),
            snapshot["url"],
            now,
            now,
        ),
    )
    row = conn.execute(
        "SELECT * FROM company_financials WHERE company_id = ? AND source = ? AND as_of = ?",
        (company["id"], snapshot["source"], snapshot["as_of"]),
    ).fetchone()
    item = dict(row) if row else {"id": cur.lastrowid, **snapshot}
    if item.get("metrics_json"):
        item["metrics"] = json.loads(item["metrics_json"])
    return item


def update_news_for_company(
    conn: sqlite3.Connection,
    security_code: str,
    limit: int | None = None,
    *,
    summarize: bool | None = None,
) -> list[dict[str, Any]]:
    company = _company(conn, security_code)
    selected_limit = limit or int(get_setting(conn, "company_news_fetch_limit", "20") or "20")
    fetch_multiplier = max(1, int(get_setting(conn, "company_news_keyword_fetch_multiplier", "4") or "4"))
    items = YahooJapanFinanceSource().fetch_news(security_code, limit=max(selected_limit * fetch_multiplier, selected_limit + 20))
    profile = get_company_news_profile(conn, company)
    min_score = float(get_setting(conn, "company_news_relevance_min_score", "0.35") or "0.35")
    max_summary_items = int(get_setting(conn, "news_summary_max_items", "12") or "12")
    should_summarize = _truthy(get_setting(conn, "news_summary_on_update", "0")) if summarize is None else summarize
    saved = 0
    summarized = 0
    for item in items:
        decision = decide_company_news(item.get("title"), item.get("provider"))
        relevance = score_company_news_candidate(item, company, profile, decision)
        if not relevance["keep"] or float(relevance["score"]) < min_score:
            continue
        item["url"] = canonical_news_url(item.get("url")) or item.get("url")
        item["content_text"] = fetch_article_text(item.get("url")) if decision.action == "summarize" and should_summarize else None
        if should_summarize and decision.action == "summarize" and summarized < max_summary_items:
            item["summary"] = summarize_news_item(conn, company={**company, "business_profile": profile}, item=item)
            summarized += 1
        else:
            item["summary"] = None
        event = upsert_source_event(
            conn,
            scope="company",
            event_type="company_news",
            company_id=int(company["id"]),
            title=item["title"],
            information_date=item["information_date"],
            published_at=item["published_at"],
            source=item["source"],
            provider=item["provider"],
            url=item["url"],
            content_text=item.get("content_text"),
            metadata={
                "provider": item.get("provider"),
                "relevance_score": relevance["score"],
                "selection_reason": relevance["reason"],
                "keyword_hits": relevance["keyword_hits"],
                "policy_action": decision.action,
                "policy_reason": decision.reason,
            },
            raw_payload=item,
        )
        record_event_triage(
            conn,
            source_event_id=int(event["id"]),
            company_id=int(company["id"]),
            action=decision.action,
            relevance_score=float(relevance["score"]),
            materiality_score=float(relevance["score"]),
            reason=relevance["reason"],
            model_name="rule",
            prompt_version=decision.reason,
        )
        if item.get("summary"):
            upsert_event_summary(
                conn,
                source_event_id=int(event["id"]),
                company_id=int(company["id"]),
                summary_text=item["summary"],
                summary_type="llm_compressed",
                model_name=get_setting(conn, "news_summary_provider", "llama_cpp") or "llama_cpp",
            )
        saved += 1
        if saved >= selected_limit:
            break
    return list_news_for_company(conn, security_code, limit=selected_limit)


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def update_disclosures_for_company(conn: sqlite3.Connection, security_code: str, limit: int = 40) -> list[dict[str, Any]]:
    company = _company(conn, security_code)
    items = YahooJapanFinanceSource().fetch_disclosures(security_code, limit=limit)
    extract_enabled = _truthy(get_setting(conn, "disclosure_pdf_extract_on_update", "1"))
    extract_limit = int(get_setting(conn, "disclosure_pdf_extract_limit", "3") or "3")
    extracted = 0
    for item in items:
        event = upsert_source_event(
            conn,
            scope="company",
            event_type="disclosure",
            company_id=int(company["id"]),
            title=item["title"],
            information_date=item["information_date"],
            published_at=item["published_at"],
            source=item["source"],
            provider="TDnet",
            url=item["url"],
            metadata={
                "document_type": item.get("document_type"),
                "summary": item.get("summary"),
                "importance_score": item.get("importance_score"),
            },
            raw_payload=item,
        )
        record_event_triage(
            conn,
            source_event_id=int(event["id"]),
            company_id=int(company["id"]),
            action="must_include" if _is_fundamental_disclosure_type(item) else "title_only",
            relevance_score=float(item.get("importance_score") or 0.5),
            materiality_score=float(item.get("importance_score") or 0.5),
            reason="適時開示は企業判断の必須情報として保存",
            model_name="rule",
            prompt_version="disclosure_policy_v2",
        )
        if item.get("summary"):
            upsert_event_summary(
                conn,
                source_event_id=int(event["id"]),
                company_id=int(company["id"]),
                summary_text=item["summary"],
                summary_type="source_excerpt",
                model_name="tdnet",
            )
        if extract_enabled and extracted < extract_limit and _should_extract_disclosure_pdf(item):
            item_with_id = {**item, "source_event_id": int(event["id"])}
            try:
                result = process_disclosure_pdf(conn, company=company, disclosure=item_with_id)
                if result.get("summary"):
                    upsert_event_summary(
                        conn,
                        source_event_id=int(event["id"]),
                        company_id=int(company["id"]),
                        summary_text=str(result["summary"]),
                        summary_type="pdf_extract",
                        model_name="pypdf",
                    )
                extracted += 1
            except DocumentExtractionError:
                continue
    return list_disclosures_for_company(conn, security_code, limit=limit)


def _should_extract_disclosure_pdf(item: dict[str, Any]) -> bool:
    if not str(item.get("url") or "").lower().endswith(".pdf"):
        return False
    return item.get("document_type") in {
        "earnings_release",
        "earnings_presentation",
        "forecast_revision",
        "dividend",
        "share_buyback",
    }


def _is_fundamental_disclosure_type(item: dict[str, Any]) -> bool:
    return item.get("document_type") in {
        "earnings_release",
        "earnings_presentation",
        "forecast_revision",
        "dividend",
        "share_buyback",
    }


def list_financials_for_company(conn: sqlite3.Connection, security_code: str, limit: int = 5) -> list[dict[str, Any]]:
    company = _company(conn, security_code)
    rows = conn.execute(
        """
        SELECT *
        FROM company_financials
        WHERE company_id = ?
        ORDER BY as_of DESC, updated_at DESC
        LIMIT ?
        """,
        (company["id"], limit),
    ).fetchall()
    items = [dict(row) for row in rows]
    for item in items:
        item["metrics"] = _loads(item.pop("metrics_json", None))
    return items


def list_news_for_company(conn: sqlite3.Connection, security_code: str, limit: int = 20) -> list[dict[str, Any]]:
    company = _company(conn, security_code)
    return _event_items(list_company_events(conn, int(company["id"]), event_types={"company_news"}, limit=limit))


def list_disclosures_for_company(conn: sqlite3.Connection, security_code: str, limit: int = 20) -> list[dict[str, Any]]:
    company = _company(conn, security_code)
    return _event_items(list_company_events(conn, int(company["id"]), event_types={"disclosure"}, limit=limit))


def _event_items(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    items = []
    for event in events:
        metadata = event.get("metadata") or {}
        items.append(
            {
                "id": event["id"],
                "source_event_id": event["id"],
                "title": event.get("title"),
                "document_type": metadata.get("document_type"),
                "published_at": event.get("published_at"),
                "information_date": event.get("information_date"),
                "source": event.get("source"),
                "provider": event.get("provider"),
                "url": event.get("url"),
                "content_text": event.get("content_text"),
                "summary": event.get("summary"),
                "importance_score": metadata.get("importance_score"),
                "relevance_score": event.get("relevance_score") or metadata.get("relevance_score"),
                "selection_reason": event.get("selection_reason") or metadata.get("selection_reason"),
                "keyword_hits": metadata.get("keyword_hits"),
            }
        )
    return items


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


def _update_company_from_snapshot(
    conn: sqlite3.Connection,
    company_id: int,
    current: dict[str, Any],
    values: dict[str, Any],
) -> None:
    name = values.get("name")
    market = values.get("market")
    industry = values.get("industry")
    should_update_name = name and (not current.get("name") or str(current.get("name", "")).startswith("未登録銘柄"))
    if not should_update_name and market == current.get("market") and industry == current.get("industry"):
        return
    conn.execute(
        """
        UPDATE companies
        SET name = COALESCE(?, name),
            market = COALESCE(?, market),
            industry = COALESCE(?, industry),
            updated_at = ?
        WHERE id = ?
        """,
        (
            name if should_update_name else None,
            market if market and not current.get("market") else None,
            industry if industry and not current.get("industry") else None,
            utc_now(),
            company_id,
        ),
    )


def _request_text(url: str, timeout_seconds: int = 30) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 stock-visualize-composer/0.1",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        raise CompanySourceError(f"{url} returned HTTP {exc.code}") from exc
    except urllib.error.URLError as exc:
        raise CompanySourceError(f"{url} request failed: {exc}") from exc


def _request_json(url: str, timeout_seconds: int = 20) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 stock-visualize-composer/0.1",
            "Accept": "application/json",
            "Accept-Language": "ja,en-US;q=0.8,en;q=0.6",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.HTTPError, urllib.error.URLError, json.JSONDecodeError):
        return {}


def _fetch_quote_fallback(security_code: str) -> dict[str, Any]:
    symbol = f"{security_code}.T"
    params = urllib.parse.urlencode({"symbols": symbol})
    payload = _request_json(f"https://query1.finance.yahoo.com/v7/finance/quote?{params}")
    result = ((payload.get("quoteResponse") or {}).get("result") or [None])[0] or {}
    if not result:
        return {"metrics": {}}
    metrics: dict[str, dict[str, Any]] = {}
    _put_metric(metrics, "market_cap", "時価総額", result.get("marketCap"), "円")
    _put_metric(metrics, "shares_issued", "発行済株式数", result.get("sharesOutstanding"), "株")
    _put_metric(metrics, "dividend_yield", "配当利回り", _percent_value(result.get("dividendYield") or result.get("trailingAnnualDividendYield")), "%")
    _put_metric(metrics, "dividend_per_share", "1株配当", result.get("trailingAnnualDividendRate") or result.get("dividendRate"), "円")
    _put_metric(metrics, "per", "PER", result.get("trailingPE"), "倍")
    _put_metric(metrics, "pbr", "PBR", result.get("priceToBook"), "倍")
    _put_metric(metrics, "eps", "EPS", result.get("epsTrailingTwelveMonths") or result.get("epsCurrentYear"), "円")
    _put_metric(metrics, "bps", "BPS", result.get("bookValue"), "円")
    return {
        "name": result.get("longName") or result.get("shortName"),
        "market": result.get("fullExchangeName") or result.get("exchange"),
        "metrics": metrics,
    }


def _put_metric(metrics: dict[str, dict[str, Any]], key: str, name: str, value: Any, suffix: str) -> None:
    if value in (None, "", "--"):
        return
    metrics[key] = {
        "name": name,
        "value": _round_metric(value),
        "suffix": suffix,
        "update_date": date.today().isoformat(),
    }


def _percent_value(value: Any) -> Any:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return value
    return parsed * 100 if 0 < parsed < 1 else parsed


def _round_metric(value: Any) -> Any:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return value
    if abs(parsed) >= 1_000_000:
        return int(parsed)
    return round(parsed, 2)


def _jsonish(text: str) -> str:
    return html.unescape(text).replace('\\"', '"').replace("\\/", "/").replace("\\u0026", "&")


def _extract_metric(text: str, key: str) -> dict[str, Any] | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*\{{(.*?)\}}', text, re.DOTALL)
    if not match:
        return None
    body = match.group(1)
    value = _extract_prop(body, "value")
    if value in (None, "", "--"):
        return None
    return {
        "name": _extract_prop(body, "name") or key,
        "value": value,
        "suffix": _extract_prop(body, "suffix"),
        "update_date": _extract_prop(body, "updateDate"),
        "update_date_meta": _extract_prop(body, "updateDateMeta"),
    }


def _extract_prop(text: str, key: str) -> Any:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*("(?:\\.|[^"])*"|null|-?\d+(?:\.\d+)?|true|false)', text)
    if not match:
        return None
    token = match.group(1)
    if token == "null":
        return None
    if token in {"true", "false"}:
        return token == "true"
    if token.startswith('"'):
        try:
            return json.loads(token)
        except json.JSONDecodeError:
            return token.strip('"')
    try:
        return float(token) if "." in token else int(token)
    except ValueError:
        return token


def _extract_first_prop(text: str, key: str) -> str | None:
    value = _extract_prop(text, key)
    return str(value) if value else None


def _extract_company_name(text: str) -> str | None:
    match = re.search(r"<title>(.*?)【", text)
    return _squash(_strip_tags(match.group(1))) if match else None


def _extract_industry_name(text: str) -> str | None:
    match = re.search(r'CommonPriceBoard__industryName[^>]*>(.*?)</a>', text)
    return _squash(_strip_tags(match.group(1))) if match else None


def _extract_next_earnings_date(text: str) -> str | None:
    match = re.search(r"次回の決算発表日は(\d{4})年(\d{1,2})月(\d{1,2})日の予定", text)
    if not match:
        return None
    return date(int(match.group(1)), int(match.group(2)), int(match.group(3))).isoformat()


def _extract_press_release_summary(text: str) -> str | None:
    match = re.search(r'"pressReleaseSummary"\s*:\s*\{(.*?)\}\s*,\s*"performance"', text, re.DOTALL)
    if match:
        summary = _extract_prop(match.group(1), "summary")
        if summary:
            return _squash(str(summary))
    match = re.search(r'PressRelease__summaryBody[^>]*>\s*<p[^>]*>(.*?)</p>', text, re.DOTALL)
    return _squash(_strip_tags(match.group(1))) if match else None


def _extract_performance_summary(text: str) -> str | None:
    match = re.search(r'performanceSummaryMessage[^>]*>(.*?)</p>', text, re.DOTALL)
    return _squash(_strip_tags(match.group(1))) if match else None


def _extract_fiscal_period(text: str) -> str | None:
    match = re.search(r"(\d{4}年\d{1,2}月期第[１２３４一二三四1-4]四半期|FY\d{4}[^\"<]{0,60})", text)
    return _squash(match.group(1)) if match else None


def _latest_metric_date(metrics: dict[str, dict[str, Any]]) -> str | None:
    dates = [
        str(metric.get("update_date_meta"))[:10]
        for metric in metrics.values()
        if metric.get("update_date_meta")
    ]
    return max(dates) if dates else None


def _split_news_text(text: str) -> dict[str, str | None]:
    clean = _squash(text)
    match = re.match(r"(.+?)(20\d{2}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2})(.+)$", clean)
    if not match:
        return {"title": clean, "published_at": None, "provider": None}
    return {
        "title": _squash(match.group(1)),
        "published_at": _parse_market_date(match.group(2)),
        "provider": _squash(match.group(3)),
    }


def _split_disclosure_text(text: str) -> dict[str, str | None]:
    clean = _squash(text)
    match = re.match(r"(.+?)(20\d{2}/\d{1,2}/\d{1,2}|\d{1,2}/\d{1,2})(?:\s+(\d{1,2}:\d{1,2}))?TDnetPDF.*$", clean)
    if not match:
        return {"title": clean, "published_at": None, "summary": "TDnet PDF"}
    return {
        "title": _squash(match.group(1)),
        "published_at": _parse_market_date(match.group(2), match.group(3)),
        "summary": "TDnet PDF",
    }


def _parse_market_date(value: str, hhmm: str | None = None) -> str | None:
    today = datetime.now(JST).date()
    try:
        if value.startswith("20"):
            year, month, day = [int(part) for part in value.split("/")]
        else:
            year = today.year
            month, day = [int(part) for part in value.split("/")]
            parsed = date(year, month, day)
            if parsed > today + timedelta(days=7):
                year -= 1
        if hhmm:
            hour_text, minute_text = hhmm.split(":")
            if len(minute_text) == 1:
                minute_text += "0"
            parsed_time = time(int(hour_text), int(minute_text[:2]), tzinfo=JST)
        else:
            parsed_time = time(0, 0, tzinfo=JST)
        return datetime.combine(date(year, month, day), parsed_time).isoformat()
    except ValueError:
        return None


def _classify_disclosure(title: str) -> str:
    if "決算短信" in title:
        return "earnings_release"
    if "決算説明" in title or "Financial Results" in title:
        return "earnings_presentation"
    if "業績予想" in title or "通期" in title and "予想" in title:
        return "forecast_revision"
    if "配当" in title:
        return "dividend"
    if "自己株式" in title:
        return "share_buyback"
    if "代表取締役" in title or "役員" in title:
        return "governance"
    return "timely_disclosure"


def _importance_score(title: str) -> float:
    document_type = _classify_disclosure(title)
    if document_type == "earnings_release":
        return 0.95
    if document_type in {"forecast_revision", "earnings_presentation"}:
        return 0.85
    if document_type in {"dividend", "share_buyback"}:
        return 0.75
    return 0.55


def _strip_tags(fragment: str) -> str:
    return re.sub(r"<[^>]+>", "", fragment)


def _squash(value: str | None) -> str:
    return re.sub(r"\s+", " ", html.unescape(value or "")).strip()


def _loads(value: str | None) -> Any:
    if not value:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None
