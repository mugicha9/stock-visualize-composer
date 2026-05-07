from __future__ import annotations

import json
import sqlite3
from typing import Any

from ..database import get_active_prompt_template, get_setting, row_to_dict, utc_now, write_update_log
from .features import build_llm_input
from .llm import provider_from_settings, validate_judgement_output
from .signal_pipeline import build_context_packet, format_context_packet_markdown


def run_short_term_judgement(
    conn: sqlite3.Connection,
    security_code: str,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> dict[str, Any]:
    company = row_to_dict(
        conn.execute(
            "SELECT * FROM companies WHERE security_code = ? AND is_active = 1",
            (security_code,),
        ).fetchone()
    )
    if company is None:
        raise ValueError(f"Company not found: {security_code}")

    started_at = utc_now()
    prompt = get_active_prompt_template(conn)
    provider = provider_from_settings(conn, provider_name, model_name)
    llm_input = build_llm_input(conn, security_code, use_llm_news_selection=provider.name != "mock")
    output = validate_judgement_output(provider.generate(prompt["template_text"], llm_input))
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO ai_judgements (
            company_id, judgement_type, target_date, action, confidence, time_horizon,
            input_json, output_json, prompt_template_id, model_provider, model_name,
            model_options_json, data_as_of, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company["id"],
            output["judgement_type"],
            llm_input["as_of"],
            output["action"],
            output["confidence"],
            output["time_horizon"],
            json.dumps(llm_input, ensure_ascii=False),
            json.dumps(output, ensure_ascii=False),
            prompt["id"],
            provider.name,
            provider.model_name,
            json.dumps({"provider": provider.name, "pipeline": "signal_context_packet_v1"}, ensure_ascii=False),
            llm_input["as_of"],
            now,
        ),
    )
    write_update_log(
        conn,
        job_name="run_short_term_judgement",
        source=provider.name,
        status="success",
        message=f"{security_code}: {output['action']}",
        metadata_json=json.dumps({"security_code": security_code, "judgement_id": cur.lastrowid}, ensure_ascii=False),
        started_at=started_at,
        finished_at=now,
    )
    saved = get_judgement(conn, int(cur.lastrowid))
    if saved is None:
        raise RuntimeError("Failed to load saved judgement")
    return saved


def build_external_advice_prompt(conn: sqlite3.Connection, security_code: str) -> dict[str, Any]:
    company = row_to_dict(
        conn.execute(
            "SELECT * FROM companies WHERE security_code = ? AND is_active = 1",
            (security_code,),
        ).fetchone()
    )
    if company is None:
        raise ValueError(f"Company not found: {security_code}")
    prompt = get_active_prompt_template(conn)
    llm_input = build_llm_input(conn, security_code)
    context_packet = build_context_packet(llm_input)
    external_context = format_context_packet_markdown(context_packet)
    text = (
        "あなたは日本株の中長期売買判断を補助するアナリストです。\n"
        "以下のシステム方針とContext Packetだけを根拠に、必ず日本語で助言してください。\n"
        "投資助言として断定せず、判断材料・条件・リスクを分けて整理してください。\n\n"
        "重要: signal_cardsを読み、technical/news/fundamental/market の方向・影響度・鮮度・根拠を比較してください。\n"
        "テクニカルが弱くても、fundamental_summaryやfundamentalのSignal Cardが価値乖離を示す場合は投資機会として検討してください。\n"
        "ニュースや開示のSignal Cardが存在する場合は、少なくとも1件を判断理由またはリスクに具体名で反映してください。\n\n"
        "## システム方針\n"
        f"{prompt['template_text']}\n\n"
        "## Context Packet Markdown\n"
        f"{external_context}\n\n"
        "## Context Packet JSON\n"
        f"{json.dumps(context_packet, ensure_ascii=False, indent=2)}\n\n"
        "## 回答してほしい内容\n"
        "1. 中長期判断: BUY / WATCH_BUY / NO_TRADE / WATCH_SELL / SELL / INSUFFICIENT_DATA のどれか\n"
        "2. ファンダメンタル面の評価\n"
        "3. テクニカル面の評価\n"
        "4. ニュース・開示・外部要因の評価\n"
        "5. エントリー条件と撤退条件\n"
        "6. 判断を保留すべきリスク\n"
    )
    return {
        "security_code": security_code,
        "company_name": company["name"],
        "prompt_template_version": prompt["version"],
        "prompt": text,
        "input": context_packet,
    }


def run_watchlist_judgements(
    conn: sqlite3.Connection,
    provider_name: str | None = None,
    list_name: str | None = None,
) -> list[dict[str, Any]]:
    selected_list = list_name or get_setting(conn, "watchlist_default", "JPX400") or "JPX400"
    rows = conn.execute(
        """
        SELECT c.security_code
        FROM watchlists w
        JOIN companies c ON c.id = w.company_id
        WHERE w.is_active = 1 AND c.is_active = 1 AND w.list_name = ?
        ORDER BY w.priority DESC, c.security_code ASC
        """,
        (selected_list,),
    ).fetchall()
    return [run_short_term_judgement(conn, row["security_code"], provider_name) for row in rows]


def get_judgement(conn: sqlite3.Connection, judgement_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT
            j.*,
            c.security_code,
            c.name AS company_name,
            c.market,
            c.industry
        FROM ai_judgements j
        JOIN companies c ON c.id = j.company_id
        WHERE j.id = ?
        """,
        (judgement_id,),
    ).fetchone()
    return _inflate_judgement(dict(row)) if row else None


def get_judgement_context(conn: sqlite3.Connection, judgement_id: int) -> dict[str, Any]:
    judgement = get_judgement(conn, judgement_id)
    if judgement is None:
        raise ValueError(f"Judgement not found: {judgement_id}")
    llm_input = judgement.get("input") if isinstance(judgement.get("input"), dict) else {}
    context_packet = build_context_packet(llm_input)
    cards = context_packet.get("signal_cards") or []
    source_items = _judgement_source_items(llm_input)
    return {
        "judgement": judgement,
        "context_packet": context_packet,
        "card_counts": _card_counts(cards),
        "source_items": source_items,
        "generated_from_saved_input": bool(llm_input),
    }


def list_judgements(
    conn: sqlite3.Connection,
    security_code: str | None = None,
    limit: int = 50,
) -> list[dict[str, Any]]:
    params: list[Any] = []
    where = ""
    if security_code:
        where = "WHERE c.security_code = ?"
        params.append(security_code)
    params.append(limit)
    rows = conn.execute(
        f"""
        SELECT
            j.*,
            c.security_code,
            c.name AS company_name,
            c.market,
            c.industry
        FROM ai_judgements j
        JOIN companies c ON c.id = j.company_id
        {where}
        ORDER BY j.created_at DESC, j.id DESC
        LIMIT ?
        """,
        params,
    ).fetchall()
    return [_inflate_judgement(dict(row)) for row in rows]


def latest_judgement_for_company(conn: sqlite3.Connection, company_id: int) -> dict[str, Any] | None:
    row = conn.execute(
        """
        SELECT *
        FROM ai_judgements
        WHERE company_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (company_id,),
    ).fetchone()
    return _inflate_judgement(dict(row)) if row else None


def _inflate_judgement(row: dict[str, Any]) -> dict[str, Any]:
    for key in ("input_json", "output_json", "model_options_json"):
        if key in row:
            try:
                row[key.replace("_json", "")] = json.loads(row[key]) if row[key] else None
            except json.JSONDecodeError:
                row[key.replace("_json", "")] = None
    return row


def _card_counts(cards: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        source_type = str(card.get("source_type") or "unknown")
        counts[source_type] = counts.get(source_type, 0) + 1
    return counts


def _judgement_source_items(llm_input: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    event_context = llm_input.get("event_context") or {}
    news_digest = event_context.get("news_digest") or {}
    fundamental_digest = event_context.get("fundamental_digest") or {}
    return {
        "news_digest_items": _compact_items(news_digest.get("latest_items"), 24),
        "financial_disclosures": _compact_items(fundamental_digest.get("financial_disclosures"), 12),
        "recent_news_candidates": _compact_items(event_context.get("recent_news_candidates"), 16),
        "recent_disclosures": _compact_items(event_context.get("recent_disclosures"), 12),
        "selected_global_news": _compact_items(event_context.get("selected_global_news"), 12),
    }


def _compact_items(value: Any, limit: int) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    result: list[dict[str, Any]] = []
    for item in value[:limit]:
        if not isinstance(item, dict):
            continue
        result.append(
            {
                key: item.get(key)
                for key in (
                    "id",
                    "type",
                    "date",
                    "published_at",
                    "information_date",
                    "source",
                    "provider",
                    "category",
                    "title",
                    "summary",
                    "url",
                    "importance_score",
                    "relevance_score",
                    "selection_reason",
                )
                if item.get(key) is not None
            }
        )
    return result
