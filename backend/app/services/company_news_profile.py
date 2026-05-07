from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from ..database import (
    COMPANY_NEWS_PROFILE_REQUIREMENTS_PROMPT,
    COMPANY_NEWS_PROFILE_SYSTEM_PROMPT,
    get_setting,
    utc_now,
)
from .local_llm import LocalLLMRequestError, llama_cpp_chat_json
from .news_policy import NewsDecision, decide_company_news
from .signal_pipeline import NEGATIVE_TERMS, POSITIVE_TERMS


PROFILE_VERSION = "company_news_profile_v1"

PROFILE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["company_terms", "business_terms", "material_terms", "exclude_terms"],
    "properties": {
        "company_terms": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "business_terms": {"type": "array", "items": {"type": "string"}},
        "material_terms": {"type": "array", "items": {"type": "string"}},
        "exclude_terms": {"type": "array", "items": {"type": "string"}},
    },
    "additionalProperties": False,
}

DEFAULT_MATERIAL_TERMS = [
    "決算",
    "業績予想",
    "上方修正",
    "下方修正",
    "増配",
    "減配",
    "自社株",
    "自己株式",
    "受注",
    "契約",
    "設備投資",
    "M&A",
    "TOB",
    "提携",
    "規制",
    "訴訟",
    "不正",
    "関税",
    "輸出規制",
]

DEFAULT_EXCLUDE_TERMS = [
    "前日に動いた株",
    "低PBR",
    "低PER",
    "ランキング",
    "アクセスランキング",
    "レーティング日報",
    "決算発表予定",
    "寄前",
    "大引け",
    "前引け",
]


def get_company_news_profile(conn: sqlite3.Connection, company: dict[str, Any]) -> dict[str, Any]:
    if not _truthy(get_setting(conn, "company_news_keyword_profile_enabled", "1")):
        return fallback_company_news_profile(company)

    existing = _load_profile(conn, int(company["id"]))
    if existing and not _is_stale(existing.get("updated_at"), conn):
        return existing

    profile = _generate_with_llm(conn, company) or fallback_company_news_profile(company)
    _save_profile(conn, int(company["id"]), profile)
    return profile


def fallback_company_news_profile(company: dict[str, Any]) -> dict[str, Any]:
    company_terms = _company_term_variants(str(company.get("name") or ""), str(company.get("security_code") or ""))
    business_terms = _compact_terms([company.get("industry"), company.get("sector")])
    return {
        "company_terms": company_terms,
        "business_terms": business_terms,
        "material_terms": DEFAULT_MATERIAL_TERMS,
        "exclude_terms": DEFAULT_EXCLUDE_TERMS,
        "generated_by": "fallback_rules",
        "prompt_version": PROFILE_VERSION,
    }


def score_company_news_candidate(
    item: dict[str, Any],
    company: dict[str, Any],
    profile: dict[str, Any],
    decision: NewsDecision | None = None,
) -> dict[str, Any]:
    title = str(item.get("title") or "")
    provider = str(item.get("provider") or "")
    text = f"{title} {provider}"
    decision = decision or decide_company_news(title, provider)
    if decision.action == "ignore":
        return {"keep": False, "score": 0.0, "reason": decision.reason, "keyword_hits": []}

    company_hits = _hits(text, profile.get("company_terms") or [])
    business_hits = _hits(text, profile.get("business_terms") or [])
    material_hits = _hits(text, profile.get("material_terms") or DEFAULT_MATERIAL_TERMS)
    exclude_hits = _hits(text, profile.get("exclude_terms") or DEFAULT_EXCLUDE_TERMS)

    relation_score = min(0.7, len(company_hits) * 0.45 + len(business_hits) * 0.22)
    material_score = min(0.55, len(material_hits) * 0.18)
    score = 0.05 + relation_score + material_score
    if decision.action == "summarize":
        score += 0.12
    if provider and re.search(r"ロイター|Reuters|Bloomberg|日経|日本経済新聞|NHK|共同|時事", provider, re.IGNORECASE):
        score += 0.08
    if exclude_hits:
        score -= min(0.55, len(exclude_hits) * 0.28)

    score = max(0.0, min(1.0, score))
    has_relation = relation_score >= 0.22
    keep = has_relation and score >= 0.25
    if not keep and relation_score > 0 and material_score >= 0.35:
        keep = True

    keyword_hits = [*company_hits, *business_hits, *material_hits]
    if exclude_hits:
        keyword_hits.extend(f"除外:{term}" for term in exclude_hits)
    reason = _reason(decision.reason, company_hits, business_hits, material_hits, exclude_hits)
    return {"keep": keep, "score": round(score, 3), "reason": reason, "keyword_hits": keyword_hits}


def _generate_with_llm(conn: sqlite3.Connection, company: dict[str, Any]) -> dict[str, Any] | None:
    timeout = min(20, int(get_setting(conn, "news_summary_timeout_seconds", "45") or "45"))
    messages = [
        {
            "role": "system",
            "content": get_setting(conn, "prompt_company_news_profile_system", COMPANY_NEWS_PROFILE_SYSTEM_PROMPT)
            or COMPANY_NEWS_PROFILE_SYSTEM_PROMPT,
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
                    },
                    "requirements": [
                        line.strip()
                        for line in (
                            get_setting(
                                conn,
                                "prompt_company_news_profile_requirements",
                                COMPANY_NEWS_PROFILE_REQUIREMENTS_PROMPT,
                            )
                            or COMPANY_NEWS_PROFILE_REQUIREMENTS_PROMPT
                        ).splitlines()
                        if line.strip()
                    ],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]
    try:
        parsed = llama_cpp_chat_json(conn, messages=messages, schema=PROFILE_SCHEMA, temperature=0.1, timeout_seconds=timeout)
    except LocalLLMRequestError:
        return None
    fallback = fallback_company_news_profile(company)
    return {
        "company_terms": _compact_terms([*(parsed.get("company_terms") or []), *fallback["company_terms"]])[:12],
        "business_terms": _compact_terms(parsed.get("business_terms") or fallback["business_terms"])[:16],
        "material_terms": _compact_terms([*(parsed.get("material_terms") or []), *DEFAULT_MATERIAL_TERMS])[:24],
        "exclude_terms": _compact_terms([*(parsed.get("exclude_terms") or []), *DEFAULT_EXCLUDE_TERMS])[:24],
        "generated_by": "llama_cpp",
        "prompt_version": PROFILE_VERSION,
    }


def _load_profile(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    row = conn.execute("SELECT * FROM company_news_profiles WHERE company_id = ?", (company_id,)).fetchone()
    if row is None:
        return None
    data = dict(row)
    return {
        "company_terms": _loads_list(data.get("company_terms_json")),
        "business_terms": _loads_list(data.get("business_terms_json")),
        "material_terms": _loads_list(data.get("material_terms_json")),
        "exclude_terms": _loads_list(data.get("exclude_terms_json")),
        "generated_by": data.get("generated_by"),
        "prompt_version": data.get("prompt_version"),
        "updated_at": data.get("updated_at"),
    }


def _save_profile(conn: sqlite3.Connection, company_id: int, profile: dict[str, Any]) -> None:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO company_news_profiles
            (company_id, company_terms_json, business_terms_json, material_terms_json, exclude_terms_json,
             generated_by, prompt_version, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(company_id) DO UPDATE SET
            company_terms_json = excluded.company_terms_json,
            business_terms_json = excluded.business_terms_json,
            material_terms_json = excluded.material_terms_json,
            exclude_terms_json = excluded.exclude_terms_json,
            generated_by = excluded.generated_by,
            prompt_version = excluded.prompt_version,
            updated_at = excluded.updated_at
        """,
        (
            company_id,
            json.dumps(profile.get("company_terms") or [], ensure_ascii=False),
            json.dumps(profile.get("business_terms") or [], ensure_ascii=False),
            json.dumps(profile.get("material_terms") or [], ensure_ascii=False),
            json.dumps(profile.get("exclude_terms") or [], ensure_ascii=False),
            profile.get("generated_by"),
            profile.get("prompt_version") or PROFILE_VERSION,
            now,
            now,
        ),
    )


def _is_stale(updated_at: Any, conn: sqlite3.Connection) -> bool:
    try:
        parsed = datetime.fromisoformat(str(updated_at).replace("Z", "+00:00"))
    except ValueError:
        return True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    days = int(get_setting(conn, "company_news_keyword_profile_refresh_days", "30") or "30")
    return datetime.now(timezone.utc) - parsed > timedelta(days=days)


def _company_term_variants(name: str, security_code: str) -> list[str]:
    base = _normalize_term(name)
    variants = [base, security_code]
    replacements = [
        "株式会社",
        "ホールディングス",
        "ＨＤ",
        "HD",
        "グループ",
        "コーポレーション",
    ]
    shortened = base
    for value in replacements:
        shortened = shortened.replace(value, "")
    variants.append(shortened)
    if shortened.endswith("業") and len(shortened) >= 5:
        variants.append(shortened[:-1])
    return _compact_terms(variants)


def _hits(text: str, terms: list[Any]) -> list[str]:
    normalized_text = _normalize_term(text).lower()
    hits = []
    for raw in terms:
        term = _normalize_term(str(raw))
        if len(term) < 2:
            continue
        if term.lower() in normalized_text:
            hits.append(term)
    return hits[:8]


def _reason(decision_reason: str, company_hits: list[str], business_hits: list[str], material_hits: list[str], exclude_hits: list[str]) -> str:
    parts = [decision_reason]
    if company_hits:
        parts.append(f"企業語: {', '.join(company_hits[:3])}")
    if business_hits:
        parts.append(f"事業語: {', '.join(business_hits[:3])}")
    if material_hits:
        parts.append(f"材料語: {', '.join(material_hits[:3])}")
    if exclude_hits:
        parts.append(f"除外語: {', '.join(exclude_hits[:3])}")
    return " / ".join(parts)


def _compact_terms(values: Any) -> list[str]:
    if values is None:
        return []
    if not isinstance(values, list):
        values = [values]
    result = []
    seen = set()
    for value in values:
        term = _normalize_term(str(value))
        if len(term) < 2 or term in seen:
            continue
        seen.add(term)
        result.append(term)
    return result


def _normalize_term(value: str) -> str:
    return re.sub(r"\s+", "", value or "").strip()


def _loads_list(value: str | None) -> list[str]:
    if not value:
        return []
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        return []
    return _compact_terms(parsed if isinstance(parsed, list) else [])


def _truthy(value: object) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}
