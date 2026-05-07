from __future__ import annotations

import sqlite3
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from ..database import get_active_prompt_template, upsert_setting, utc_now
from ..deps import get_db


router = APIRouter(prefix="/prompts", tags=["prompts"])

SETTING_PROMPTS = [
    ("prompt_news_summary_system", "ニュース要約: system"),
    ("prompt_news_summary_task", "ニュース要約: task"),
    ("prompt_material_assessment_system", "材料評価: system"),
    ("prompt_material_assessment_task", "材料評価: task"),
    ("prompt_news_relevance_system", "ニュース選別: system"),
    ("prompt_news_relevance_policy", "ニュース選別: policy"),
    ("prompt_company_news_profile_system", "企業別キーワード: system"),
    ("prompt_company_news_profile_requirements", "企業別キーワード: requirements"),
    ("prompt_final_judgement_user_instruction", "最終判断: user instruction"),
    ("prompt_final_judgement_repair_instruction", "最終判断: repair instruction"),
]


@router.get("")
def list_prompts(conn: sqlite3.Connection = Depends(get_db)) -> dict[str, Any]:
    final_prompt = get_active_prompt_template(conn)
    rows = {
        row["key"]: dict(row)
        for row in conn.execute(
            """
            SELECT key, value, updated_at
            FROM app_settings
            WHERE key LIKE 'prompt_%'
            ORDER BY key ASC
            """
        ).fetchall()
    }
    prompts = [
        {
            "key": "final_judgement",
            "label": "最終判断: system policy",
            "value": final_prompt["template_text"],
            "updated_at": final_prompt["created_at"],
            "source": "ai_prompt_templates",
        }
    ]
    for key, label in SETTING_PROMPTS:
        row = rows.get(key)
        prompts.append(
            {
                "key": key,
                "label": label,
                "value": row["value"] if row else "",
                "updated_at": row["updated_at"] if row else None,
                "source": "app_settings",
            }
        )
    return {"prompts": prompts}


@router.put("/{key}")
def update_prompt(
    key: str,
    payload: dict[str, str],
    conn: sqlite3.Connection = Depends(get_db),
) -> dict[str, Any]:
    value = payload.get("value", "")
    if not value.strip():
        raise HTTPException(status_code=400, detail="prompt must not be empty")
    if key == "final_judgement":
        return _update_final_prompt(conn, value)
    allowed = {item[0] for item in SETTING_PROMPTS}
    if key not in allowed:
        raise HTTPException(status_code=404, detail=f"Unknown prompt: {key}")
    row = upsert_setting(conn, key, value)
    return {"key": key, "label": dict(SETTING_PROMPTS).get(key, key), "value": row["value"], "updated_at": row["updated_at"], "source": "app_settings"}


def _update_final_prompt(conn: sqlite3.Connection, value: str) -> dict[str, Any]:
    now = utc_now()
    conn.execute(
        """
        UPDATE ai_prompt_templates
        SET is_active = 0
        WHERE judgement_type = ?
        """,
        ("short_term",),
    )
    conn.execute(
        """
        INSERT INTO ai_prompt_templates
            (name, judgement_type, version, template_text, model_name, is_active, created_at)
        VALUES (?, ?, ?, ?, NULL, 1, ?)
        ON CONFLICT(name, version) DO UPDATE SET
            template_text = excluded.template_text,
            is_active = 1,
            created_at = excluded.created_at
        """,
        ("short_term_default", "short_term", "custom", value, now),
    )
    return {"key": "final_judgement", "label": "最終判断: system policy", "value": value, "updated_at": now, "source": "ai_prompt_templates"}
