from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..database import NEWS_RELEVANCE_POLICY_PROMPT, NEWS_RELEVANCE_SYSTEM_PROMPT, get_setting, utc_now
from .content_summaries import fetch_article_text, summarize_news_item
from .local_llm import LocalLLMRequestError, llama_cpp_chat_json
from .signal_pipeline import NEGATIVE_TERMS, POSITIVE_TERMS


RANKING_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["selected"],
    "properties": {
        "selected": {
            "type": "array",
            "items": {
                "type": "object",
                "required": ["id", "relevance_score", "reason"],
                "properties": {
                    "id": {"type": "integer"},
                    "relevance_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "reason": {"type": "string"},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


def prepare_relevant_news(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    company_news: list[dict[str, Any]],
    global_news: list[dict[str, Any]],
    max_company: int = 15,
    max_global: int = 30,
    allow_fetch: bool = True,
    use_llm_ranking: bool = True,
) -> dict[str, list[dict[str, Any]]]:
    return {
        "company_news": _prepare_group(
            conn,
            company=company,
            items=company_news,
            group="company_news",
            max_items=max_company,
            table="news_articles",
            allow_fetch=allow_fetch,
            use_llm_ranking=use_llm_ranking,
        ),
        "global_news": _prepare_group(
            conn,
            company=company,
            items=global_news,
            group="global_news",
            max_items=max_global,
            table="global_news",
            allow_fetch=allow_fetch,
            use_llm_ranking=use_llm_ranking,
        ),
    }


def _prepare_group(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    items: list[dict[str, Any]],
    group: str,
    max_items: int,
    table: str,
    allow_fetch: bool,
    use_llm_ranking: bool,
) -> list[dict[str, Any]]:
    if not items:
        return []
    ranked = _rank_with_llm(conn, company=company, items=items, group=group, max_items=max_items) if use_llm_ranking else _fallback_ranking(company=company, items=items, max_items=max_items)
    selected_by_id = {int(item["id"]): item for item in ranked}
    selected: list[dict[str, Any]] = []
    now = utc_now()
    for item in items:
        ranking = selected_by_id.get(int(item["id"]))
        if not ranking:
            continue
        prepared = dict(item)
        if allow_fetch and not prepared.get("content_text"):
            prepared["content_text"] = fetch_article_text(prepared.get("url"))
            if prepared["content_text"]:
                conn.execute(f"UPDATE {table} SET content_text = ?, updated_at = ? WHERE id = ?", (prepared["content_text"], now, item["id"]))
        if allow_fetch and not prepared.get("summary"):
            prepared["summary"] = summarize_news_item(conn, company=company, item=prepared)
            if prepared["summary"] and table in {"news_articles", "global_news"}:
                conn.execute(f"UPDATE {table} SET summary = ?, updated_at = ? WHERE id = ?", (prepared["summary"], now, item["id"]))
        selected.append(
            {
                **prepared,
                "relevance_score": ranking.get("relevance_score"),
                "selection_reason": ranking.get("reason"),
                "summary": prepared.get("summary") or _fallback_summary(prepared),
            }
        )
        if len(selected) >= max_items:
            break
    return selected


def _rank_with_llm(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    items: list[dict[str, Any]],
    group: str,
    max_items: int,
) -> list[dict[str, Any]]:
    llm_result = _try_llm_ranking(conn, company=company, items=items, group=group, max_items=max_items)
    if llm_result:
        return llm_result[:max_items]
    return _fallback_ranking(company=company, items=items, max_items=max_items)


def _try_llm_ranking(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    items: list[dict[str, Any]],
    group: str,
    max_items: int,
) -> list[dict[str, Any]]:
    timeout = min(12, int(get_setting(conn, "news_summary_timeout_seconds", "45") or "45"))
    title_rows = [
        {
            "id": int(item["id"]),
            "title": item.get("title"),
            "published_at": item.get("published_at") or item.get("information_date"),
            "provider": item.get("provider"),
        }
        for item in items[:30]
    ]
    selection_policy = [
        line.strip()
        for line in (get_setting(conn, "prompt_news_relevance_policy", NEWS_RELEVANCE_POLICY_PROMPT) or NEWS_RELEVANCE_POLICY_PROMPT).splitlines()
        if line.strip()
    ]
    messages = [
        {
            "role": "system",
            "content": get_setting(conn, "prompt_news_relevance_system", NEWS_RELEVANCE_SYSTEM_PROMPT)
            or NEWS_RELEVANCE_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "company": {
                        "security_code": company.get("security_code"),
                        "name": company.get("name"),
                        "market": company.get("market"),
                        "sector": company.get("sector"),
                        "industry": company.get("industry"),
                        "business_profile": company.get("business_profile"),
                    },
                    "group": group,
                    "max_items": max_items,
                    "selection_policy": selection_policy,
                    "titles": title_rows,
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]
    try:
        parsed = llama_cpp_chat_json(conn, messages=messages, schema=RANKING_SCHEMA, temperature=0.1, timeout_seconds=timeout)
    except LocalLLMRequestError:
        return []
    valid_ids = {int(item["id"]) for item in items}
    selected = []
    for row in parsed.get("selected") or []:
        if int(row.get("id", -1)) not in valid_ids:
            continue
        selected.append(
            {
                "id": int(row["id"]),
                "relevance_score": max(0.0, min(1.0, float(row.get("relevance_score") or 0))),
                "reason": str(row.get("reason") or "LLMが重要と判定"),
            }
        )
    selected.sort(key=lambda row: row["relevance_score"], reverse=True)
    return selected


def _fallback_ranking(*, company: dict[str, Any], items: list[dict[str, Any]], max_items: int) -> list[dict[str, Any]]:
    company_terms = [str(company.get(key) or "") for key in ("name", "sector", "industry")]
    ranked = []
    for item in items:
        text = f"{item.get('title') or ''} {item.get('provider') or ''} {item.get('category') or ''}"
        score = 0.15
        for term in company_terms:
            if term and term in text:
                score += 0.28
        for term, value in POSITIVE_TERMS.items():
            if term in text:
                score += min(abs(value) / 3, 0.25)
        for term, value in NEGATIVE_TERMS.items():
            if term in text:
                score += min(abs(value) / 3, 0.25)
        if re.search(r"決算|業績予想|配当|自社株|自己株式|M&A|TOB|関税|地政学|金利|為替|原油|規制|経済安全保障", text):
            score += 0.3
        ranked.append({"id": int(item["id"]), "relevance_score": min(score, 1.0), "reason": "キーワードで重要度を推定"})
    ranked.sort(key=lambda row: row["relevance_score"], reverse=True)
    return ranked[:max_items]


def _fallback_summary(item: dict[str, Any]) -> str | None:
    basis = "本文不足" if item.get("content_text") else "タイトルのみ"
    text = item.get("content_text") or item.get("title")
    if not text:
        return None
    normalized = re.sub(r"\s+", " ", str(text)).strip()
    clipped = normalized[:360] + ("..." if len(normalized) > 360 else "")
    return f"分類: 不明 要約: {clipped} 材料性: 不明 根拠: {basis}"
