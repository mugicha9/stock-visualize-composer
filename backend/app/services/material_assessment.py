from __future__ import annotations

import json
import re
import sqlite3
from typing import Any

from ..database import get_setting
from .local_llm import LocalLLMRequestError, llama_cpp_chat_json


ASSESSMENT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["assessments"],
    "properties": {
        "assessments": {
            "type": "array",
            "items": {
                "type": "object",
                "required": [
                    "id",
                    "direction",
                    "direction_score",
                    "impact_score",
                    "confidence",
                    "company_relevance",
                    "expectation_gap",
                    "reason",
                    "risk_notes",
                    "used_evidence",
                ],
                "properties": {
                    "id": {"type": "integer"},
                    "direction": {"type": "string", "enum": ["bullish", "bearish", "neutral", "uncertain"]},
                    "direction_score": {"type": "number", "minimum": -1, "maximum": 1},
                    "impact_score": {"type": "number", "minimum": 0, "maximum": 1},
                    "confidence": {"type": "number", "minimum": 0, "maximum": 1},
                    "company_relevance": {"type": "number", "minimum": 0, "maximum": 1},
                    "expectation_gap": {"type": "string", "enum": ["positive", "negative", "neutral", "unknown"]},
                    "reason": {"type": "string"},
                    "risk_notes": {"type": "array", "items": {"type": "string"}},
                    "used_evidence": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
        }
    },
    "additionalProperties": False,
}


DEFAULT_SYSTEM_PROMPT = """あなたは日本株の材料評価担当です。
入力されたニュース・適時開示・全体ニュースを、対象企業のcompany_profileに照らして評価してください。
単純な良材料/悪材料の一般論ではなく、その企業の主力事業、需要先、原材料、規制、市況、財務指標にどう影響するかで判断します。
市場期待やコンセンサスとのギャップが入力にない場合は、expectation_gapをunknownにしてください。
本文や要約にない事実を作らず、不明な場合はneutralまたはuncertainにしてください。
出力はJSONのみ、理由とリスクは日本語で書いてください。
"""

DEFAULT_TASK_PROMPT = """各itemについて、direction_score、impact_score、confidence、company_relevanceを返してください。
direction_scoreはこの企業にとっての中長期方向性です。
impact_scoreは方向と独立した重要度です。
キーワードだけで強い方向を付けず、企業との関係が弱い場合はcompany_relevanceとconfidenceを下げてください。
"""


def assess_material_items(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    items: list[dict[str, Any]],
    as_of: str | None,
    use_llm: bool,
) -> list[dict[str, Any]]:
    if not items:
        return []
    max_items = max(1, int(get_setting(conn, "material_assessment_max_items", "16") or "16"))
    batch_size = max(1, int(get_setting(conn, "material_assessment_batch_size", "4") or "4"))
    selected = items[:max_items]
    assessments: dict[int, dict[str, Any]] = {}
    errors: dict[int, str] = {}
    if use_llm and _truthy(get_setting(conn, "material_assessment_enabled", "1")):
        for offset in range(0, len(selected), batch_size):
            batch = selected[offset : offset + batch_size]
            batch_assessments, error = _llm_assess_with_error(conn, company=company, items=batch, as_of=as_of)
            if error:
                for index in range(offset, offset + len(batch)):
                    errors[index] = error
                continue
            for index, assessment in batch_assessments.items():
                assessments[offset + index] = assessment
    result: list[dict[str, Any]] = []
    for index, item in enumerate(items):
        assessment = assessments.get(index) if index < max_items else None
        error = errors.get(index) if index < max_items else "material_assessment_max_itemsを超えたためLLM評価対象外です。"
        result.append({**item, "material_assessment": assessment or _fallback_assessment(item, error=error)})
    return result


def _llm_assess(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    items: list[dict[str, Any]],
    as_of: str | None,
) -> dict[int, dict[str, Any]]:
    assessments, _ = _llm_assess_with_error(conn, company=company, items=items, as_of=as_of)
    return assessments


def _llm_assess_with_error(
    conn: sqlite3.Connection,
    *,
    company: dict[str, Any],
    items: list[dict[str, Any]],
    as_of: str | None,
) -> tuple[dict[int, dict[str, Any]], str | None]:
    timeout = int(get_setting(conn, "material_assessment_timeout_seconds", "60") or "60")
    messages = [
        {
            "role": "system",
            "content": get_setting(conn, "prompt_material_assessment_system", DEFAULT_SYSTEM_PROMPT)
            or DEFAULT_SYSTEM_PROMPT,
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "as_of": as_of,
                    "company": {
                        "security_code": company.get("security_code"),
                        "name": company.get("name"),
                        "sector": company.get("sector"),
                        "industry": company.get("industry"),
                        "business_profile": company.get("business_profile"),
                    },
                    "task": get_setting(conn, "prompt_material_assessment_task", DEFAULT_TASK_PROMPT)
                    or DEFAULT_TASK_PROMPT,
                    "items": [_assessment_item(index, item) for index, item in enumerate(items)],
                },
                ensure_ascii=False,
                separators=(",", ":"),
            ),
        },
    ]
    try:
        parsed = llama_cpp_chat_json(conn, messages=messages, schema=ASSESSMENT_SCHEMA, temperature=0.1, timeout_seconds=timeout)
    except LocalLLMRequestError as exc:
        return {}, _clip_error(str(exc))
    assessments: dict[int, dict[str, Any]] = {}
    for row in parsed.get("assessments") or []:
        try:
            index = int(row.get("id"))
        except (TypeError, ValueError):
            continue
        if 0 <= index < len(items):
            assessments[index] = _normalize_assessment(row, provider="llama_cpp")
    if not assessments:
        return {}, "LLM材料評価のJSONに有効なassessmentsがありません。"
    return assessments, None


def _assessment_item(index: int, item: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": index,
        "type": item.get("type"),
        "date": item.get("date") or item.get("information_date") or item.get("published_at"),
        "title": item.get("title"),
        "summary": item.get("summary"),
        "source": item.get("source"),
        "provider": item.get("provider"),
        "importance_score": item.get("importance_score"),
        "relevance_score": item.get("relevance_score"),
        "selection_reason": item.get("selection_reason"),
    }


def _normalize_assessment(row: dict[str, Any], *, provider: str) -> dict[str, Any]:
    direction_score = _clamp(_num(row.get("direction_score")) if row.get("direction_score") is not None else 0.0, -1.0, 1.0)
    impact_score = _clamp(_num(row.get("impact_score")) if row.get("impact_score") is not None else 0.25, 0.0, 1.0)
    confidence = _clamp(_num(row.get("confidence")) if row.get("confidence") is not None else 0.35, 0.0, 1.0)
    relevance = _clamp(_num(row.get("company_relevance")) if row.get("company_relevance") is not None else 0.45, 0.0, 1.0)
    direction = str(row.get("direction") or "uncertain")
    if direction == "uncertain":
        direction_score = 0.0
        confidence = min(confidence, 0.45)
    return {
        "provider": provider,
        "direction": direction,
        "direction_score": round(direction_score, 3),
        "impact_score": round(impact_score, 3),
        "confidence": round(confidence, 3),
        "company_relevance": round(relevance, 3),
        "expectation_gap": row.get("expectation_gap") or "unknown",
        "reason": str(row.get("reason") or "材料評価の理由は限定的です。"),
        "risk_notes": [str(item) for item in row.get("risk_notes") or [] if str(item).strip()][:4],
        "used_evidence": [str(item) for item in row.get("used_evidence") or [] if str(item).strip()][:4],
    }


def _fallback_assessment(item: dict[str, Any], *, error: str | None = None) -> dict[str, Any]:
    summary = str(item.get("summary") or "")
    materiality = _summary_field(summary, "材料性")
    if materiality == "ポジティブ":
        direction, score = "bullish", 0.2
    elif materiality == "ネガティブ":
        direction, score = "bearish", -0.2
    else:
        direction, score = "neutral", 0.0
    importance = _num(item.get("importance_score"))
    relevance = _num(item.get("relevance_score"))
    impact = max(0.25, min(0.55, max(importance or 0, relevance or 0.35)))
    return {
        "provider": "llm_error_fallback" if error else "summary_fallback",
        "direction": direction,
        "direction_score": score,
        "impact_score": round(impact, 3),
        "confidence": 0.32,
        "company_relevance": round(_clamp(relevance if relevance is not None else 0.45, 0.0, 1.0), 3),
        "expectation_gap": "unknown",
        "reason": (
            f"LLM材料評価に失敗したため、保存済み要約の材料性だけから弱く評価しています。失敗理由: {error}"
            if error
            else "LLM材料評価がないため、保存済み要約の材料性だけから弱く評価しています。"
        ),
        "risk_notes": ["市場期待とのギャップは未評価です。", *( [f"LLM材料評価エラー: {error}"] if error else [] )],
        "used_evidence": [item.get("title") or ""],
    }


def _summary_field(summary: str, label: str) -> str | None:
    if not summary:
        return None
    labels = "分類|要約|要点|注意|材料性|根拠"
    match = re.search(rf"(?:^|\s){label}[:：]\s*(.*?)(?=\s(?:{labels})[:：]|$)", summary)
    return match.group(1).strip() if match else None


def _num(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(str(value).replace(",", "").replace("%", ""))
    except ValueError:
        return None


def _clamp(value: float | None, low: float, high: float) -> float:
    if value is None:
        return low
    return max(low, min(high, value))


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _clip_error(value: str, limit: int = 180) -> str:
    text = re.sub(r"\s+", " ", value).strip()
    return text[:limit] + ("..." if len(text) > limit else "")
