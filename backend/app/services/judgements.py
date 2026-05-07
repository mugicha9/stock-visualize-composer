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
    context_packet = build_context_packet(llm_input)
    context_packet_id = _save_context_packet(conn, int(company["id"]), context_packet)
    output = validate_judgement_output(provider.generate(prompt["template_text"], llm_input))
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO ai_judgements (
            company_id, judgement_type, target_date, action, confidence, time_horizon,
            input_json, output_json, prompt_template_id, context_packet_id, model_provider, model_name,
            model_options_json, data_as_of, created_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
            context_packet_id,
            provider.name,
            provider.model_name,
            json.dumps(
                {
                    "provider": provider.name,
                    "pipeline": "signal_context_packet_v2",
                    "context_packet_id": context_packet_id,
                    **(getattr(provider, "last_metadata", {}) or {}),
                },
                ensure_ascii=False,
            ),
            llm_input["as_of"],
            now,
        ),
    )
    judgement_id = int(cur.lastrowid)
    _link_judgement_signals(conn, judgement_id, context_packet_id, output)
    _cleanup_context_packets(conn, int(company["id"]))
    write_update_log(
        conn,
        job_name="run_short_term_judgement",
        source=provider.name,
        status="success",
        message=f"{security_code}: {output['action']}",
        metadata_json=json.dumps({"security_code": security_code, "judgement_id": judgement_id}, ensure_ascii=False),
        started_at=started_at,
        finished_at=now,
    )
    saved = get_judgement(conn, judgement_id)
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
    saved_context_packet = _load_context_packet(conn, judgement)
    context_packet = saved_context_packet or build_context_packet(llm_input)
    cards = context_packet.get("signal_cards") or []
    source_items = _judgement_source_items(llm_input)
    return {
        "judgement": judgement,
        "context_packet": context_packet,
        "card_counts": _card_counts(cards),
        "source_items": source_items,
        "generated_from_saved_input": bool(llm_input),
        "loaded_from_context_packet": bool(saved_context_packet),
    }


def _save_context_packet(conn: sqlite3.Connection, company_id: int, context_packet: dict[str, Any]) -> int:
    now = utc_now()
    signal_ids = [str(card.get("signal_id")) for card in context_packet.get("signal_cards") or [] if card.get("signal_id")]
    packet_json = json.dumps(context_packet, ensure_ascii=False, separators=(",", ":"))
    cur = conn.execute(
        """
        INSERT INTO context_packets
            (company_id, judgement_type, as_of, build_version, packet_json,
             included_signal_ids_json, excluded_signal_ids_json, token_estimate, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            company_id,
            context_packet.get("judgement_type") or "mid_long_term",
            context_packet.get("as_of") or "",
            "signal_context_packet_v2",
            packet_json,
            json.dumps(signal_ids, ensure_ascii=False),
            json.dumps([], ensure_ascii=False),
            max(1, len(packet_json) // 4),
            now,
        ),
    )
    context_packet_id = int(cur.lastrowid)
    for card in context_packet.get("signal_cards") or []:
        if not isinstance(card, dict) or not card.get("signal_id"):
            continue
        conn.execute(
            """
            INSERT INTO signal_cards
                (company_id, context_packet_id, signal_id, source_type, source_id, source_event_id, source_name,
                 horizon, direction, direction_score, impact_score, confidence, freshness_score,
                 relevance_score, summary, evidence_json, risk_notes_json, payload_json,
                 valid_from, valid_until, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, ?)
            ON CONFLICT(context_packet_id, signal_id) DO UPDATE SET
                payload_json = excluded.payload_json
            """,
            (
                company_id,
                context_packet_id,
                card.get("signal_id"),
                card.get("source_type"),
                card.get("source_id"),
                card.get("source_event_id"),
                card.get("source_name"),
                card.get("horizon") or "mid_long_term",
                card.get("direction") or "neutral",
                float(card.get("direction_score") or 0),
                float(card.get("impact_score") or 0),
                float(card.get("confidence") or 0),
                float(card.get("freshness_score") or 0),
                float(card.get("relevance_score") or 0),
                card.get("summary") or "",
                json.dumps(card.get("evidence") or [], ensure_ascii=False),
                json.dumps(card.get("risk_notes") or [], ensure_ascii=False),
                json.dumps(card, ensure_ascii=False, separators=(",", ":")),
                card.get("published_at") or context_packet.get("as_of"),
                now,
            ),
        )
    return context_packet_id


def _link_judgement_signals(
    conn: sqlite3.Connection,
    judgement_id: int,
    context_packet_id: int,
    output: dict[str, Any],
) -> None:
    conn.execute("UPDATE signal_cards SET judgement_id = ? WHERE context_packet_id = ?", (judgement_id, context_packet_id))
    rows = conn.execute(
        "SELECT id, signal_id FROM signal_cards WHERE context_packet_id = ?",
        (context_packet_id,),
    ).fetchall()
    card_ids = {row["signal_id"]: int(row["id"]) for row in rows}
    now = utc_now()
    for signal_id in output.get("used_signal_ids") or []:
        card_id = card_ids.get(signal_id)
        if card_id is None:
            continue
        conn.execute(
            """
            INSERT INTO judgement_signal_links
                (judgement_id, signal_card_id, signal_id, usage_type, reason, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(judgement_id, signal_id, usage_type) DO NOTHING
            """,
            (judgement_id, card_id, signal_id, "used", "LLM output used_signal_ids", now),
        )


def _load_context_packet(conn: sqlite3.Connection, judgement: dict[str, Any]) -> dict[str, Any] | None:
    context_packet_id = judgement.get("context_packet_id")
    if not context_packet_id:
        return None
    row = conn.execute("SELECT packet_json FROM context_packets WHERE id = ?", (context_packet_id,)).fetchone()
    if row is None:
        return None
    try:
        packet = json.loads(row["packet_json"])
    except json.JSONDecodeError:
        return None
    if not isinstance(packet, dict):
        return None
    used_ids = set((judgement.get("output") or {}).get("used_signal_ids") or [])
    cards = []
    for card_row in conn.execute(
        "SELECT id, signal_id, payload_json FROM signal_cards WHERE context_packet_id = ? ORDER BY impact_score DESC, id ASC",
        (context_packet_id,),
    ).fetchall():
        try:
            card = json.loads(card_row["payload_json"]) if card_row["payload_json"] else {}
        except json.JSONDecodeError:
            card = {}
        if not isinstance(card, dict):
            card = {}
        card.setdefault("signal_id", card_row["signal_id"])
        card["db_id"] = card_row["id"]
        card["used_by_judgement"] = card_row["signal_id"] in used_ids
        cards.append(card)
    if cards:
        packet["signal_cards"] = cards
    return packet


def _cleanup_context_packets(conn: sqlite3.Connection, company_id: int) -> None:
    retention = int(get_setting(conn, "context_packet_retention_per_company", "80") or "80")
    if retention <= 0:
        return
    old_rows = conn.execute(
        """
        SELECT id
        FROM context_packets
        WHERE company_id = ?
        ORDER BY created_at DESC, id DESC
        LIMIT -1 OFFSET ?
        """,
        (company_id, retention),
    ).fetchall()
    old_ids = [int(row["id"]) for row in old_rows]
    if not old_ids:
        return
    placeholders = ",".join("?" for _ in old_ids)
    conn.execute(f"UPDATE ai_judgements SET context_packet_id = NULL WHERE context_packet_id IN ({placeholders})", old_ids)
    old_card_ids = [
        int(row["id"])
        for row in conn.execute(f"SELECT id FROM signal_cards WHERE context_packet_id IN ({placeholders})", old_ids).fetchall()
    ]
    if old_card_ids:
        card_placeholders = ",".join("?" for _ in old_card_ids)
        conn.execute(f"DELETE FROM judgement_signal_links WHERE signal_card_id IN ({card_placeholders})", old_card_ids)
    conn.execute(f"DELETE FROM signal_cards WHERE context_packet_id IN ({placeholders})", old_ids)
    conn.execute(f"DELETE FROM context_packets WHERE id IN ({placeholders})", old_ids)


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
