from __future__ import annotations

import json
import re
import sqlite3
import urllib.error
import urllib.request
from typing import Any

from ..config import (
    LLAMA_CPP_BASE_URL,
    LLAMA_CPP_MIN_P,
    LLAMA_CPP_MODEL_NAME,
    LLAMA_CPP_PRESENCE_PENALTY,
    LLAMA_CPP_REPEAT_PENALTY,
    LLAMA_CPP_TEMPERATURE,
    LLAMA_CPP_TIMEOUT_SECONDS,
    LLAMA_CPP_TOP_K,
    LLAMA_CPP_TOP_P,
)
from ..database import get_setting


class LocalLLMRequestError(RuntimeError):
    pass


def llama_cpp_chat_json(
    conn: sqlite3.Connection,
    *,
    messages: list[dict[str, str]],
    schema: dict[str, Any] | None = None,
    model_name: str | None = None,
    temperature: float | None = None,
    timeout_seconds: int | None = None,
) -> dict[str, Any]:
    base_url = (get_setting(conn, "llama_cpp_base_url", LLAMA_CPP_BASE_URL) or LLAMA_CPP_BASE_URL).rstrip("/")
    selected_model = model_name or get_setting(conn, "llama_cpp_model_name", LLAMA_CPP_MODEL_NAME) or LLAMA_CPP_MODEL_NAME
    timeout = timeout_seconds or int(
        get_setting(conn, "llama_cpp_timeout_seconds", str(LLAMA_CPP_TIMEOUT_SECONDS)) or LLAMA_CPP_TIMEOUT_SECONDS
    )
    return llama_cpp_chat_json_request(
        base_url=base_url,
        model_name=selected_model,
        messages=messages,
        schema=schema,
        temperature=temperature
        if temperature is not None
        else float(get_setting(conn, "llama_cpp_temperature", str(LLAMA_CPP_TEMPERATURE)) or LLAMA_CPP_TEMPERATURE),
        top_p=float(get_setting(conn, "llama_cpp_top_p", str(LLAMA_CPP_TOP_P)) or LLAMA_CPP_TOP_P),
        top_k=int(get_setting(conn, "llama_cpp_top_k", str(LLAMA_CPP_TOP_K)) or LLAMA_CPP_TOP_K),
        min_p=float(get_setting(conn, "llama_cpp_min_p", str(LLAMA_CPP_MIN_P)) or LLAMA_CPP_MIN_P),
        presence_penalty=float(
            get_setting(conn, "llama_cpp_presence_penalty", str(LLAMA_CPP_PRESENCE_PENALTY))
            or LLAMA_CPP_PRESENCE_PENALTY
        ),
        repeat_penalty=float(
            get_setting(conn, "llama_cpp_repeat_penalty", str(LLAMA_CPP_REPEAT_PENALTY)) or LLAMA_CPP_REPEAT_PENALTY
        ),
        timeout_seconds=timeout,
    )


def llama_cpp_chat_json_request(
    *,
    base_url: str,
    model_name: str,
    messages: list[dict[str, str]],
    schema: dict[str, Any] | None,
    temperature: float,
    top_p: float,
    top_k: int,
    min_p: float,
    presence_penalty: float,
    repeat_penalty: float,
    timeout_seconds: int,
) -> dict[str, Any]:
    body = {
        "model": model_name,
        "messages": messages,
        "stream": False,
        "temperature": temperature,
        "top_p": top_p,
        "top_k": top_k,
        "min_p": min_p,
        "presence_penalty": presence_penalty,
        "repeat_penalty": repeat_penalty,
    }
    if schema:
        body["json_schema"] = schema
    else:
        body["response_format"] = {"type": "json_object"}

    try:
        data = _post_chat_completion(base_url, body, timeout_seconds)
    except LocalLLMRequestError as exc:
        if schema and _should_retry_json_object(str(exc)):
            fallback_body = dict(body)
            fallback_body.pop("json_schema", None)
            fallback_body["response_format"] = {"type": "json_object"}
            data = _post_chat_completion(base_url, fallback_body, timeout_seconds)
        else:
            raise

    content = _choice_content(data)
    if not content:
        raise LocalLLMRequestError("response did not include choices[0].message.content")
    try:
        return parse_json_object(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise LocalLLMRequestError("response content was not a JSON object") from exc


def _post_chat_completion(base_url: str, body: dict[str, Any], timeout_seconds: int) -> dict[str, Any]:
    request = urllib.request.Request(
        f"{base_url}/v1/chat/completions",
        data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raise LocalLLMRequestError(f"HTTP {exc.code}: {_http_error_detail(exc)}") from exc
    except json.JSONDecodeError as exc:
        raise LocalLLMRequestError("response was not valid JSON") from exc
    except (TimeoutError, urllib.error.URLError) as exc:
        raise LocalLLMRequestError(str(exc)) from exc


def _choice_content(data: dict[str, Any]) -> str | None:
    choices = data.get("choices")
    if not isinstance(choices, list) or not choices:
        return None
    message = choices[0].get("message") if isinstance(choices[0], dict) else None
    if not isinstance(message, dict):
        return None
    content = message.get("content")
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for item in content:
            if isinstance(item, dict) and isinstance(item.get("text"), str):
                parts.append(item["text"])
            elif isinstance(item, str):
                parts.append(item)
        return "\n".join(parts) if parts else None
    return None


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = re.sub(r"<think>.*?</think>", "", text.strip(), flags=re.DOTALL | re.IGNORECASE).strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    try:
        parsed = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        if not match:
            raise
        parsed = json.loads(match.group(0))
    if not isinstance(parsed, dict):
        raise ValueError("LLM output must be a JSON object")
    return parsed


def _http_error_detail(exc: urllib.error.HTTPError) -> str:
    try:
        raw = exc.read().decode("utf-8", errors="replace")
    except Exception:
        raw = ""
    if not raw:
        return exc.reason or "empty response body"
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        return raw.strip()
    if isinstance(parsed, dict):
        message = parsed.get("error") or parsed.get("detail") or parsed.get("message")
        if message:
            return str(message)
    return raw.strip()


def _should_retry_json_object(message: str) -> bool:
    lowered = message.lower()
    return "json_schema" in lowered or "grammar" in lowered or "response_format" in lowered
