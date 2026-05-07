from __future__ import annotations

import json
import re
import sqlite3
from abc import ABC, abstractmethod
from typing import Any

from ..config import (
    LLAMA_CPP_MIN_P,
    LLAMA_CPP_MODEL_NAME,
    LLAMA_CPP_PRESENCE_PENALTY,
    LLAMA_CPP_REPEAT_PENALTY,
    LLAMA_CPP_TEMPERATURE,
    LLAMA_CPP_TIMEOUT_SECONDS,
    LLAMA_CPP_TOP_K,
    LLAMA_CPP_TOP_P,
)
from ..database import FINAL_JUDGEMENT_REPAIR_INSTRUCTION, FINAL_JUDGEMENT_USER_INSTRUCTION, get_setting
from .local_llm import LocalLLMRequestError, llama_cpp_chat_json_request
from .signal_pipeline import build_final_judgement_input


ALLOWED_ACTIONS = {
    "BUY",
    "WATCH_BUY",
    "NO_TRADE",
    "WATCH_SELL",
    "SELL",
    "INSUFFICIENT_DATA",
}

OUTPUT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": [
        "judgement_type",
        "action",
        "confidence",
        "time_horizon",
        "summary",
        "positive_factors",
        "negative_factors",
        "entry_conditions",
        "exit_conditions",
        "risk_notes",
        "used_signal_ids",
    ],
    "properties": {
        "judgement_type": {"type": "string", "enum": ["mid_long_term"]},
        "action": {
            "type": "string",
            "enum": ["BUY", "WATCH_BUY", "NO_TRADE", "WATCH_SELL", "SELL", "INSUFFICIENT_DATA"],
        },
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "time_horizon": {"type": "string"},
        "summary": {"type": "string"},
        "positive_factors": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "negative_factors": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "entry_conditions": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "exit_conditions": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "risk_notes": {"type": "array", "items": {"type": "string"}, "minItems": 1},
        "used_signal_ids": {"type": "array", "items": {"type": "string"}},
        "used_signal_types": {
            "type": "array",
            "items": {"type": "string", "enum": ["technical", "news", "fundamental", "market"]},
        },
    },
    "additionalProperties": False,
}

NATURAL_LANGUAGE_OUTPUT_FIELDS = [
    "summary",
    "positive_factors",
    "negative_factors",
    "entry_conditions",
    "exit_conditions",
    "risk_notes",
]


class LLMProvider(ABC):
    name: str
    model_name: str | None
    last_metadata: dict[str, Any]

    @abstractmethod
    def generate(self, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        raise NotImplementedError


class MockProvider(LLMProvider):
    name = "mock"

    def __init__(self, model_name: str | None = "mock-short-term-v0.1") -> None:
        self.model_name = model_name
        self.last_metadata = {"provider": self.name, "grounding": {"repair_mode": "none", "issues": []}}

    def generate(self, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        del prompt
        features = payload.get("price_features", {})
        warnings = payload.get("data_quality", {}).get("warnings", [])
        if warnings:
            return _judgement(
                action="INSUFFICIENT_DATA",
                confidence=0.35,
                summary="判断に必要な株価データまたはテクニカル指標が不足しています。",
                positive=["保存済みデータから最低限の文脈は確認できます。"],
                negative=[f"データ品質警告: {', '.join(warnings)}"],
                entry=["不足データを更新し、移動平均と出来高倍率を再計算する。"],
                exit_=["データ鮮度が確認できるまで新規判断を保留する。"],
                risks=["日次データが古い、または履歴不足の可能性があります。"],
            )

        trend_short = features.get("trend_short")
        trend_middle = features.get("trend_middle")
        change_5d = features.get("change_5d_pct") or 0
        change_20d = features.get("change_20d_pct") or 0
        volume_ratio = features.get("volume_ratio_5d") or 0
        recent_high_break = bool(features.get("recent_high_break"))
        recent_low_break = bool(features.get("recent_low_break"))
        price_vs_ma25 = features.get("price_vs_ma_25_pct") or 0
        context_positive, context_negative, context_risks = _contextual_notes(payload)
        value_opportunity = _value_opportunity(payload)

        if recent_low_break or trend_short == "down":
            if value_opportunity.get("level") in {"strong_value_dislocation", "moderate_value_support"}:
                strong = value_opportunity.get("level") == "strong_value_dislocation"
                return _judgement(
                    action="WATCH_BUY" if strong else "NO_TRADE",
                    confidence=0.6 if strong else 0.54,
                    summary=(
                        "短期テクニカルは悪化していますが、ファンダメンタル面では価値乖離候補があり、反転条件を待つ監視局面です。"
                        if strong
                        else "短期テクニカルは弱い一方、ファンダメンタルが下支えになり得るため、機械的な売りではなく条件待ちが妥当です。"
                    ),
                    positive=[
                        "下落によりファンダメンタル面の割安・還元・収益性が投資機会になり得ます。",
                        *value_opportunity.get("signals", [])[:3],
                        *context_positive,
                    ],
                    negative=[
                        "短期トレンドが下向きです。",
                        "直近安値更新または弱い値動きが確認されます。",
                        *value_opportunity.get("risks", [])[:2],
                        *context_negative,
                    ],
                    entry=[
                        "下落が一巡し、終値で5日線または25日線を回復する。",
                        "出来高を伴う陽線、または決算・開示通過後の悪材料出尽くしを確認する。",
                    ],
                    exit_=[
                        "価値支援の根拠となる決算・財務指標が悪化する。",
                        "下落が継続し、ファンダメンタル悪化を示す開示が出る。",
                    ],
                    risks=["割安に見えても下落トレンドが続く可能性があります。", *context_risks],
                )
            action = "SELL" if trend_middle == "down" and recent_low_break else "WATCH_SELL"
            confidence = 0.68 if action == "SELL" else 0.58
            return _judgement(
                action=action,
                confidence=confidence,
                summary="短期トレンドが悪化しており、下値更新または移動平均割れを警戒する局面です。",
                positive=["下落時の反発余地はありますが、買い根拠は限定的です。", *context_positive],
                negative=["短期トレンドが下向きです。", "直近安値更新または弱い値動きが確認されます。", *context_negative],
                entry=["5日線を回復し、出来高を伴って反発するまで買いを見送る。"],
                exit_=["終値で25日線を下回る状態が続く。", "直近安値を出来高増で更新する。"],
                risks=["短期需給が悪化している可能性があります。", *context_risks],
            )

        if trend_short == "up" and trend_middle == "up" and recent_high_break and volume_ratio >= 1.2:
            overheated = change_5d >= 8 or change_20d >= 20 or price_vs_ma25 >= 12
            return _judgement(
                action="WATCH_BUY" if overheated else "BUY",
                confidence=0.72 if not overheated else 0.64,
                summary=(
                    "上昇トレンド、出来高増加、高値更新が揃っています。"
                    if not overheated
                    else "上昇基調は強い一方、短期上昇後の過熱感があるため押し目監視が妥当です。"
                ),
                positive=[
                    "終値が主要移動平均線を上回っています。",
                    "出来高が5日平均比で増加しています。",
                    "直近高値を更新しています。",
                    *context_positive,
                ],
                negative=[
                    "短期上昇率が高い場合は追いかけ買いのリスクがあります。",
                    "日次データのため場中の変化は反映されません。",
                    *context_negative,
                ],
                entry=["25日線を割らずに反発する。", "出来高を伴って直近高値を再更新する。"],
                exit_=["終値で25日線を明確に下回る。", "出来高を伴う大陰線が出る。"],
                risks=["中長期判断では決算、財務、外部要因の継続確認が必要です。", *context_risks],
            )

        if trend_short == "up" and price_vs_ma25 > 0:
            return _judgement(
                action="WATCH_BUY",
                confidence=0.56,
                summary="短期は上向きですが、出来高や高値更新の確認が十分ではないため監視が妥当です。",
                positive=["終値が25日線を上回っています。", "短期トレンドは上向きです。", *context_positive],
                negative=["高値更新や出来高増加の根拠が限定的です。", *context_negative],
                entry=["出来高倍率が1.2倍以上に上昇する。", "直近高値を終値で更新する。"],
                exit_=["25日線を終値で下回る。", "短期トレンドがneutralまたはdownに転じる。"],
                risks=["明確な売買シグナルが揃う前の監視段階です。", *context_risks],
            )

        return _judgement(
            action="NO_TRADE",
            confidence=0.52,
            summary="中長期で買いを積極化するだけのファンダメンタル、ニュース、価格確認材料が不足しています。",
            positive=["大きな悪化シグナルは限定的です。", *context_positive],
            negative=["トレンドが不明瞭です。", "出来高や高値更新の裏付けが弱い状態です。", *context_negative],
            entry=["上昇トレンドと出来高増加が同時に確認される。"],
            exit_=["直近安値を更新する。", "主要移動平均を下回る状態が続く。"],
            risks=["無理に売買判断を出す局面ではありません。", *context_risks],
        )


class LlamaCppProvider(LLMProvider):
    name = "llama_cpp"

    def __init__(
        self,
        base_url: str,
        model_name: str,
        temperature: float = LLAMA_CPP_TEMPERATURE,
        top_p: float = LLAMA_CPP_TOP_P,
        top_k: int = LLAMA_CPP_TOP_K,
        min_p: float = LLAMA_CPP_MIN_P,
        presence_penalty: float = LLAMA_CPP_PRESENCE_PENALTY,
        repeat_penalty: float = LLAMA_CPP_REPEAT_PENALTY,
        timeout_seconds: int = LLAMA_CPP_TIMEOUT_SECONDS,
        max_attempts: int = 5,
        auto_repair: bool = True,
        user_instruction: str = FINAL_JUDGEMENT_USER_INSTRUCTION,
        repair_instruction: str = FINAL_JUDGEMENT_REPAIR_INSTRUCTION,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model_name = model_name
        self.temperature = temperature
        self.top_p = top_p
        self.top_k = top_k
        self.min_p = min_p
        self.presence_penalty = presence_penalty
        self.repeat_penalty = repeat_penalty
        self.timeout_seconds = timeout_seconds
        self.max_attempts = max(1, min(10, int(max_attempts)))
        self.auto_repair = auto_repair
        self.user_instruction = user_instruction
        self.repair_instruction = repair_instruction

    def generate(self, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
        model_input = build_final_judgement_input(payload)
        context_packet = model_input["context_packet"]
        self.last_metadata = {
            "provider": self.name,
            "model_name": self.model_name,
            "grounding": {"repair_mode": "none", "issues": [], "attempts": 0},
        }
        messages = [
            {
                "role": "system",
                "content": (
                    prompt
                    + "\n\n現在の入力はContext Packet JSONです。"
                    + "signal_cards、technical_summary、news_summary、fundamental_summary、aggregated_signalを同じ入力根拠として扱ってください。"
                    + "\n\n返答は売買判断JSONだけにしてください。"
                    + "Context Packetを繰り返してはいけません。"
                    + "説明文、Markdown、コードブロックは禁止です。"
                    + "judgement_type/action/time_horizon/used_signal_types/used_signal_idsはSchemaで指定された英字コードやIDのままにしてください。"
                    + "summary/positive_factors/negative_factors/entry_conditions/exit_conditions/risk_notesは必ず自然な日本語の文章で書いてください。"
                    + "これらの説明文フィールドでは英語の文、英語の見出し、英語の箇条書きは禁止です。"
                    + "PER/PBR/ROE/EPSなど一般的な指標略語は使ってよいですが、説明は日本語にしてください。"
                    + "推論過程は出力せず、最終判断JSONだけを返してください。"
                ),
            },
            {
                "role": "user",
                "content": (
                    self.user_instruction.strip()
                    + "\n\nContext Packet JSON:\n"
                    + json.dumps(model_input, ensure_ascii=False, separators=(",", ":"))
                ),
            },
        ]
        last_issues: list[str] = []
        last_parsed: dict[str, Any] | None = None
        for _ in range(self.max_attempts):
            self.last_metadata["grounding"]["attempts"] += 1
            try:
                parsed = llama_cpp_chat_json_request(
                    base_url=self.base_url,
                    model_name=self.model_name,
                    messages=messages,
                    schema=OUTPUT_SCHEMA,
                    temperature=self.temperature,
                    top_p=self.top_p,
                    top_k=self.top_k,
                    min_p=self.min_p,
                    presence_penalty=self.presence_penalty,
                    repeat_penalty=self.repeat_penalty,
                    timeout_seconds=self.timeout_seconds,
                )
            except LocalLLMRequestError as exc:
                raise RuntimeError(f"llama.cpp request failed: {exc}{_llama_cpp_error_hint(str(exc), self.model_name)}") from exc
            last_parsed = parsed
            last_issues = _grounding_issues(parsed, context_packet)
            if not last_issues:
                self.last_metadata["grounding"]["issues"] = []
                return parsed
            self.last_metadata["grounding"]["issues"] = last_issues
            messages.append(
                {
                    "role": "user",
                    "content": (
                        self.repair_instruction.strip()
                        + f"\n問題: {', '.join(last_issues)}。"
                        + "\nContext Packet JSON:\n"
                        + json.dumps(model_input, ensure_ascii=False, separators=(",", ":"))
                    ),
                }
            )
        if self.auto_repair and last_parsed is not None:
            repaired = _repair_grounding_output(last_parsed, last_issues, context_packet)
            repaired_issues = _grounding_issues(repaired, context_packet)
            self.last_metadata["grounding"]["repair_mode"] = "safe_field_fallback"
            self.last_metadata["grounding"]["issues_before_fallback"] = last_issues
            self.last_metadata["grounding"]["issues"] = repaired_issues
            if not repaired_issues:
                return repaired
        raise RuntimeError(f"LLM output failed grounding checks: {', '.join(last_issues)}")


def provider_from_settings(
    conn: sqlite3.Connection,
    provider_name: str | None = None,
    model_name: str | None = None,
) -> LLMProvider:
    selected = (provider_name or get_setting(conn, "default_llm_provider", "mock") or "mock").strip()
    if selected == "llama_cpp":
        return LlamaCppProvider(
            base_url=get_setting(conn, "llama_cpp_base_url", "http://127.0.0.1:10000") or "http://127.0.0.1:10000",
            model_name=model_name or get_setting(conn, "llama_cpp_model_name", LLAMA_CPP_MODEL_NAME) or LLAMA_CPP_MODEL_NAME,
            temperature=float(
                get_setting(conn, "llama_cpp_temperature", str(LLAMA_CPP_TEMPERATURE)) or LLAMA_CPP_TEMPERATURE
            ),
            top_p=float(get_setting(conn, "llama_cpp_top_p", str(LLAMA_CPP_TOP_P)) or LLAMA_CPP_TOP_P),
            top_k=int(get_setting(conn, "llama_cpp_top_k", str(LLAMA_CPP_TOP_K)) or LLAMA_CPP_TOP_K),
            min_p=float(get_setting(conn, "llama_cpp_min_p", str(LLAMA_CPP_MIN_P)) or LLAMA_CPP_MIN_P),
            presence_penalty=float(
                get_setting(conn, "llama_cpp_presence_penalty", str(LLAMA_CPP_PRESENCE_PENALTY))
                or LLAMA_CPP_PRESENCE_PENALTY
            ),
            repeat_penalty=float(
                get_setting(conn, "llama_cpp_repeat_penalty", str(LLAMA_CPP_REPEAT_PENALTY))
                or LLAMA_CPP_REPEAT_PENALTY
            ),
            timeout_seconds=int(
                get_setting(conn, "llama_cpp_timeout_seconds", str(LLAMA_CPP_TIMEOUT_SECONDS))
                or LLAMA_CPP_TIMEOUT_SECONDS
            ),
            max_attempts=_int_setting(conn, "llm_judgement_max_attempts", 5),
            auto_repair=_truthy(get_setting(conn, "llm_grounding_auto_repair_enabled", "1")),
            user_instruction=get_setting(conn, "prompt_final_judgement_user_instruction", FINAL_JUDGEMENT_USER_INSTRUCTION)
            or FINAL_JUDGEMENT_USER_INSTRUCTION,
            repair_instruction=get_setting(conn, "prompt_final_judgement_repair_instruction", FINAL_JUDGEMENT_REPAIR_INSTRUCTION)
            or FINAL_JUDGEMENT_REPAIR_INSTRUCTION,
        )
    if selected == "mock":
        return MockProvider(model_name=model_name)
    raise ValueError(f"Unsupported LLM provider: {selected}")


def _llama_cpp_error_hint(detail: str, model_name: str) -> str:
    lowered = detail.lower()
    if "unable to load model" in lowered or "failed to load model" in lowered:
        return (
            f" / 対処: 設定モデル '{model_name}' をロードできません。"
            "llama.cpp Dockerコンテナ、モデルファイルの配置、RAM/VRAM、GPUランタイムを確認してください。"
        )
    if "connection refused" in lowered or "urlopen error" in lowered:
        return " / 対処: llama.cpp server が起動しているか、llama_cpp_base_url が正しいか確認してください。"
    return ""


def _int_setting(conn: sqlite3.Connection, key: str, default: int) -> int:
    try:
        return int(get_setting(conn, key, str(default)) or default)
    except ValueError:
        return default


def _truthy(value: str | None) -> bool:
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _grounding_issues(output: dict[str, Any], payload: dict[str, Any]) -> list[str]:
    output_text = " ".join(_natural_language_output_values(output))
    input_text = json.dumps(payload, ensure_ascii=False)
    checks = {
        "業界平均との比較": ["業界平均", "同業平均"],
        "市場平均との比較": ["市場平均"],
        "未入力の業績修正": ["上方修正", "下方修正", "業績予想修正", "業績修正"],
        "未入力の景気判断": ["景気回復", "景気悪化"],
        "未入力の政策効果": ["政策支援が見込まれる", "政策支援を受ける", "補助金効果"],
    }
    issues = []
    for label, terms in checks.items():
        if any(term in output_text and term not in input_text for term in terms):
            issues.append(label)
    if _contains_english_sentence(output_text):
        issues.append("英語文の混入")
    for key in ["positive_factors", "negative_factors", "entry_conditions", "exit_conditions", "risk_notes"]:
        values = output.get(key)
        if not isinstance(values, list) or not values or any(not isinstance(item, str) or not item.strip() for item in values):
            issues.append(f"{key}の空欄")
    valid_signal_ids = {
        str(card.get("signal_id"))
        for card in payload.get("signal_cards") or []
        if isinstance(card, dict) and card.get("signal_id")
    }
    used_signal_ids = output.get("used_signal_ids")
    if valid_signal_ids:
        if not isinstance(used_signal_ids, list) or any(str(item) not in valid_signal_ids for item in used_signal_ids):
            issues.append("used_signal_idsの不整合")
        elif not used_signal_ids:
            issues.append("used_signal_idsの空欄")
    warnings = (payload.get("data_quality") or {}).get("warnings") or (payload.get("data_status") or {}).get("missing_data") or []
    if output.get("action") == "INSUFFICIENT_DATA" and not warnings:
        issues.append("データ不足の誤判定")
    if not warnings and any(term in output_text for term in ["情報不足", "データ不足", "情報が不足", "データが不足"]):
        issues.append("情報不足の誤判定")
    if not warnings and output.get("confidence") == 0:
        issues.append("confidence 0 の誤判定")
    return issues


def _repair_grounding_output(output: dict[str, Any], issues: list[str], payload: dict[str, Any]) -> dict[str, Any]:
    repaired = dict(output)
    for field in NATURAL_LANGUAGE_OUTPUT_FIELDS:
        repaired[field] = _safe_grounded_value(field)
    valid_signal_ids = [
        str(card.get("signal_id"))
        for card in payload.get("signal_cards") or []
        if isinstance(card, dict) and card.get("signal_id")
    ]
    repaired["used_signal_ids"] = valid_signal_ids[:3]

    warnings = (payload.get("data_quality") or {}).get("warnings") or (payload.get("data_status") or {}).get("missing_data") or []
    if not warnings:
        if repaired.get("action") == "INSUFFICIENT_DATA":
            repaired["action"] = "NO_TRADE"
            try:
                confidence = float(repaired.get("confidence") or 0)
            except (TypeError, ValueError):
                confidence = 0.0
            repaired["confidence"] = max(confidence, 0.45)
    return repaired


def _safe_grounded_value(field: str) -> str | list[str]:
    fallback = {
        "summary": "入力済みのSignal Cardを根拠に、中長期では条件付きで監視する局面です。",
        "positive_factors": "入力済みのファンダメンタル、ニュース、価格材料のうち支援材料を確認します。",
        "negative_factors": "入力済み材料の方向感が限定的で、悪材料の継続確認が必要です。",
        "entry_conditions": "入力済み材料の改善と価格の確認条件がそろうまで慎重に判断します。",
        "exit_conditions": "決算、開示、価格動向の悪化が入力で確認された場合は撤退を検討します。",
        "risk_notes": "入力にない事実は根拠にせず、保存済み材料の更新で判断を見直します。",
    }.get(field, "入力済み材料だけを根拠に判断します。")
    return fallback if field == "summary" else [fallback]


def _natural_language_output_values(output: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field in NATURAL_LANGUAGE_OUTPUT_FIELDS:
        values.extend(_string_values(output.get(field)))
    return values


def _contains_english_sentence(text: str) -> bool:
    for match in re.finditer(r"\b[A-Za-z][A-Za-z0-9 ,.;:'\"!?()&+-]{18,}", text):
        segment = match.group(0).strip()
        if segment and not _allowed_alpha_segment(segment):
            return True
    return False


def _allowed_alpha_segment(segment: str) -> bool:
    tokens = re.findall(r"[A-Za-z]+", segment)
    if not tokens:
        return True
    return all(token.isupper() or len(token) <= 2 for token in tokens)


def _string_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        result: list[str] = []
        for item in value:
            result.extend(_string_values(item))
        return result
    if isinstance(value, dict):
        result: list[str] = []
        for item in value.values():
            result.extend(_string_values(item))
        return result
    return []


def validate_judgement_output(output: dict[str, Any]) -> dict[str, Any]:
    missing = [field for field in OUTPUT_SCHEMA["required"] if field not in output]
    if missing:
        raise ValueError(f"LLM output missing required fields: {', '.join(missing)}")
    if output["judgement_type"] != "mid_long_term":
        raise ValueError("judgement_type must be mid_long_term")
    if output["action"] not in ALLOWED_ACTIONS:
        raise ValueError(f"Unsupported action: {output['action']}")
    confidence = output["confidence"]
    if isinstance(confidence, str):
        try:
            confidence = float(confidence.rstrip("%"))
        except ValueError as exc:
            raise ValueError("confidence must be a number between 0 and 1") from exc
    if isinstance(confidence, (int, float)) and 1 < confidence <= 100:
        confidence = confidence / 100
    if not isinstance(confidence, (int, float)) or confidence < 0 or confidence > 1:
        raise ValueError("confidence must be a number between 0 and 1")
    output["confidence"] = float(confidence)
    for key in ["positive_factors", "negative_factors", "entry_conditions", "exit_conditions", "risk_notes"]:
        if not isinstance(output[key], list) or not all(isinstance(item, str) for item in output[key]):
            raise ValueError(f"{key} must be a string array")
    if not isinstance(output["used_signal_ids"], list) or not all(isinstance(item, str) for item in output["used_signal_ids"]):
        raise ValueError("used_signal_ids must be a string array")
    if not isinstance(output["summary"], str) or not output["summary"].strip():
        raise ValueError("summary must be a non-empty string")
    return output


def _contextual_notes(payload: dict[str, Any]) -> tuple[list[str], list[str], list[str]]:
    event_context = payload.get("event_context") or {}
    fundamental = event_context.get("fundamental_context") or {}
    positive: list[str] = []
    negative: list[str] = []
    risks: list[str] = []

    valuation = fundamental.get("valuation") or {}
    profitability = fundamental.get("profitability") or {}
    safety = fundamental.get("financial_safety") or {}
    returns = fundamental.get("shareholder_return") or {}
    earnings = fundamental.get("earnings_event") or {}

    if profitability.get("direction") == "strong":
        positive.append("ROE水準から収益性は中長期判断の下支え材料です。")
    elif profitability.get("direction") == "weak":
        negative.append("ROE水準が低く、収益性面の支援材料は弱いです。")

    if valuation.get("direction") == "undemanding":
        positive.append("PER/PBRは過度な割高感を示しておらず、押し目では評価余地があります。")
    elif valuation.get("direction") == "expensive":
        negative.append("PER/PBR面では割高感があり、上値追いには慎重さが必要です。")

    if safety.get("direction") == "strong":
        positive.append("自己資本比率から財務安全性は一定の下値耐性として見られます。")
    elif safety.get("direction") == "weak":
        negative.append("自己資本比率が低く、悪材料時の下値リスクに注意が必要です。")

    if returns.get("direction") == "supportive":
        positive.append("配当利回りは株主還元面の支援材料です。")

    days_to_earnings = earnings.get("days_to_earnings")
    if isinstance(days_to_earnings, int) and -3 <= days_to_earnings <= 14:
        risks.append("決算発表が近く、イベント通過まで値動きが不安定になり得ます。")

    fundamental_digest = event_context.get("fundamental_digest") or {}
    financial_disclosures = fundamental_digest.get("financial_disclosures") or []
    if financial_disclosures:
        top_titles = [str(item.get("title")) for item in financial_disclosures[:2] if item.get("title")]
        if top_titles:
            risks.append(f"決算・財務関連の開示「{'」「'.join(top_titles)}」を判断条件に入れる必要があります。")

    news_digest = event_context.get("news_digest") or {}
    digest_items = news_digest.get("latest_items") or []
    if digest_items:
        top_titles = [str(item.get("title")) for item in digest_items[:2] if item.get("title")]
        if top_titles:
            risks.append(f"直近材料として「{'」「'.join(top_titles)}」を売買条件に反映する必要があります。")

    global_news = event_context.get("selected_global_news") or []
    if global_news:
        top_titles = [str(item.get("title")) for item in global_news[:2] if item.get("title")]
        if top_titles:
            risks.append(f"外部要因として「{'」「'.join(top_titles)}」を確認する必要があります。")

    return positive[:4], negative[:4], risks[:4]


def _value_opportunity(payload: dict[str, Any]) -> dict[str, Any]:
    event_context = payload.get("event_context") or {}
    digest = event_context.get("fundamental_digest") or {}
    opportunity = digest.get("opportunity")
    if isinstance(opportunity, dict):
        return opportunity
    snapshot = digest.get("snapshot") or {}
    opportunity = snapshot.get("opportunity") if isinstance(snapshot, dict) else None
    return opportunity if isinstance(opportunity, dict) else {}


def _judgement(
    *,
    action: str,
    confidence: float,
    summary: str,
    positive: list[str],
    negative: list[str],
    entry: list[str],
    exit_: list[str],
    risks: list[str],
) -> dict[str, Any]:
    return {
        "judgement_type": "mid_long_term",
        "action": action,
        "confidence": confidence,
        "time_horizon": "3_months_to_1_year",
        "summary": summary,
        "positive_factors": positive,
        "negative_factors": negative,
        "entry_conditions": entry,
        "exit_conditions": exit_,
        "risk_notes": risks,
        "used_signal_ids": [],
    }
