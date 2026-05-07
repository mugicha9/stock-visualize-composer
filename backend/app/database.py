from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator

from .config import (
    APP_SETTINGS_PATH,
    DATABASE_PATH,
    COMPANY_NEWS_FETCH_LIMIT,
    COMPANY_NEWS_KEYWORD_FETCH_MULTIPLIER,
    COMPANY_NEWS_KEYWORD_PROFILE_ENABLED,
    COMPANY_NEWS_KEYWORD_PROFILE_REFRESH_DAYS,
    COMPANY_NEWS_RELEVANCE_MIN_SCORE,
    DEFAULT_LLM_PROVIDER,
    DISCLOSURE_PDF_EXTRACT_LIMIT,
    DISCLOSURE_PDF_EXTRACT_ON_UPDATE,
    DISCLOSURE_PDF_MAX_PAGES,
    DISCLOSURE_PDF_OCR_ENABLED,
    GLOBAL_NEWS_FETCH_LIMIT_PER_SOURCE,
    LLM_NEWS_SELECTION_MAX_COMPANY,
    LLM_NEWS_SELECTION_MAX_GLOBAL,
    LLAMA_CPP_ALIAS,
    LLAMA_CPP_BASE_URL,
    LLAMA_CPP_CHAT_TEMPLATE_KWARGS,
    LLAMA_CPP_CONTAINER_MODELS_DIR,
    LLAMA_CPP_CONTAINER_NAME,
    LLAMA_CPP_CONTAINER_PORT,
    LLAMA_CPP_CONTEXT_LENGTH,
    LLAMA_CPP_DOCKER_ENV_JSON,
    LLAMA_CPP_DOCKER_GPUS,
    LLAMA_CPP_DOCKER_RESTART,
    LLAMA_CPP_EXTRA_ARGS,
    LLAMA_CPP_GPU_LAYERS,
    LLAMA_CPP_HOST,
    LLAMA_CPP_HOST_MODELS_DIR,
    LLAMA_CPP_IMAGE,
    LLAMA_CPP_MIN_P,
    LLAMA_CPP_MODEL_FILE,
    LLAMA_CPP_MODEL_NAME,
    LLAMA_CPP_N_PARALLEL,
    LLAMA_CPP_NCMOE,
    LLAMA_CPP_NO_MMAP,
    LLAMA_CPP_PORT,
    LLAMA_CPP_PRESENCE_PENALTY,
    LLAMA_CPP_REASONING,
    LLAMA_CPP_REASONING_BUDGET,
    LLAMA_CPP_REPEAT_PENALTY,
    LLAMA_CPP_TEMPERATURE,
    LLAMA_CPP_TIMEOUT_SECONDS,
    LLAMA_CPP_TOP_K,
    LLAMA_CPP_TOP_P,
    NEWS_SUMMARY_MAX_ITEMS,
    NEWS_SUMMARY_ON_UPDATE,
    NEWS_SUMMARY_PROVIDER,
    NEWS_SUMMARY_TIMEOUT_SECONDS,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def connect_db() -> sqlite3.Connection:
    DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def db_session() -> Iterator[sqlite3.Connection]:
    conn = connect_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def row_to_dict(row: sqlite3.Row | None) -> dict[str, Any] | None:
    if row is None:
        return None
    return {key: row[key] for key in row.keys()}


def rows_to_dicts(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    return [row_to_dict(row) or {} for row in rows]


def init_db() -> None:
    schema_path = Path(__file__).with_name("schema.sql")
    with db_session() as conn:
        conn.executescript(schema_path.read_text(encoding="utf-8"))
        ensure_current_schema(conn)
        from .services.information_dates import ensure_information_date_columns, refresh_information_dates

        ensure_information_date_columns(conn)
        seed_default_settings(conn)
        seed_default_prompt(conn)
        refresh_information_dates(conn)


def ensure_current_schema(conn: sqlite3.Connection) -> None:
    _ensure_column(conn, "news_articles", "content_text", "TEXT")
    _ensure_column(conn, "news_articles", "relevance_score", "REAL")
    _ensure_column(conn, "news_articles", "selection_reason", "TEXT")
    _ensure_column(conn, "news_articles", "keyword_hits", "TEXT")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS company_news_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company_id INTEGER NOT NULL UNIQUE,
            company_terms_json TEXT,
            business_terms_json TEXT,
            material_terms_json TEXT,
            exclude_terms_json TEXT,
            generated_by TEXT,
            prompt_version TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,

            FOREIGN KEY (company_id) REFERENCES companies(id)
        )
        """
    )
    conn.execute(
        """
        CREATE INDEX IF NOT EXISTS idx_company_news_profiles_company
        ON company_news_profiles(company_id)
        """
    )


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in columns:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def seed_default_settings(conn: sqlite3.Connection) -> None:
    now = utc_now()
    defaults = default_app_settings()
    db_values = {
        row["key"]: row["value"]
        for row in conn.execute("SELECT key, value FROM app_settings").fetchall()
    }
    file_values = load_settings_file({**defaults, **db_values})
    settings = {**defaults, **file_values}
    save_settings_file(settings)
    for key, value in settings.items():
        conn.execute(
            """
            INSERT INTO app_settings (key, value, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(key) DO UPDATE SET
                value = excluded.value,
                updated_at = excluded.updated_at
            """,
            (key, value, now),
        )


def default_app_settings() -> dict[str, str]:
    return {
        "default_llm_provider": DEFAULT_LLM_PROVIDER,
        "llama_cpp_base_url": LLAMA_CPP_BASE_URL,
        "llama_cpp_model_name": LLAMA_CPP_MODEL_NAME,
        "llama_cpp_timeout_seconds": str(LLAMA_CPP_TIMEOUT_SECONDS),
        "llama_cpp_temperature": str(LLAMA_CPP_TEMPERATURE),
        "llama_cpp_top_p": str(LLAMA_CPP_TOP_P),
        "llama_cpp_top_k": str(LLAMA_CPP_TOP_K),
        "llama_cpp_min_p": str(LLAMA_CPP_MIN_P),
        "llama_cpp_presence_penalty": str(LLAMA_CPP_PRESENCE_PENALTY),
        "llama_cpp_repeat_penalty": str(LLAMA_CPP_REPEAT_PENALTY),
        "llm_judgement_max_attempts": "5",
        "llm_grounding_auto_repair_enabled": "1",
        "llama_cpp_container_name": LLAMA_CPP_CONTAINER_NAME,
        "llama_cpp_image": LLAMA_CPP_IMAGE,
        "llama_cpp_docker_restart": LLAMA_CPP_DOCKER_RESTART,
        "llama_cpp_docker_gpus": LLAMA_CPP_DOCKER_GPUS,
        "llama_cpp_host_models_dir": LLAMA_CPP_HOST_MODELS_DIR,
        "llama_cpp_container_models_dir": LLAMA_CPP_CONTAINER_MODELS_DIR,
        "llama_cpp_model_file": LLAMA_CPP_MODEL_FILE,
        "llama_cpp_alias": LLAMA_CPP_ALIAS,
        "llama_cpp_host": LLAMA_CPP_HOST,
        "llama_cpp_port": LLAMA_CPP_PORT,
        "llama_cpp_container_port": LLAMA_CPP_CONTAINER_PORT,
        "llama_cpp_context_length": LLAMA_CPP_CONTEXT_LENGTH,
        "llama_cpp_n_parallel": LLAMA_CPP_N_PARALLEL,
        "llama_cpp_ncmoe": LLAMA_CPP_NCMOE,
        "llama_cpp_gpu_layers": LLAMA_CPP_GPU_LAYERS,
        "llama_cpp_no_mmap": LLAMA_CPP_NO_MMAP,
        "llama_cpp_chat_template_kwargs": LLAMA_CPP_CHAT_TEMPLATE_KWARGS,
        "llama_cpp_reasoning": LLAMA_CPP_REASONING,
        "llama_cpp_reasoning_budget": LLAMA_CPP_REASONING_BUDGET,
        "llama_cpp_docker_env_json": LLAMA_CPP_DOCKER_ENV_JSON,
        "llama_cpp_extra_args": LLAMA_CPP_EXTRA_ARGS,
        "default_timeframe": "1d",
        "data_source_price": "yahoo_finance",
        "data_source_company_info": "yahoo_finance_japan",
        "data_source_news": "yahoo_finance_news",
        "data_source_disclosures": "tdnet_via_yahoo_finance",
        "data_source_external_factors": "official_rss",
        "company_news_fetch_limit": str(COMPANY_NEWS_FETCH_LIMIT),
        "company_news_keyword_profile_enabled": COMPANY_NEWS_KEYWORD_PROFILE_ENABLED,
        "company_news_keyword_profile_refresh_days": str(COMPANY_NEWS_KEYWORD_PROFILE_REFRESH_DAYS),
        "company_news_relevance_min_score": str(COMPANY_NEWS_RELEVANCE_MIN_SCORE),
        "company_news_keyword_fetch_multiplier": str(COMPANY_NEWS_KEYWORD_FETCH_MULTIPLIER),
        "global_news_fetch_limit_per_source": str(GLOBAL_NEWS_FETCH_LIMIT_PER_SOURCE),
        "llm_news_selection_max_company": str(LLM_NEWS_SELECTION_MAX_COMPANY),
        "llm_news_selection_max_global": str(LLM_NEWS_SELECTION_MAX_GLOBAL),
        "news_summary_provider": NEWS_SUMMARY_PROVIDER,
        "news_summary_max_items": str(NEWS_SUMMARY_MAX_ITEMS),
        "news_summary_timeout_seconds": str(NEWS_SUMMARY_TIMEOUT_SECONDS),
        "news_summary_on_update": NEWS_SUMMARY_ON_UPDATE,
        "prompt_news_summary_system": NEWS_SUMMARY_SYSTEM_PROMPT,
        "prompt_news_summary_task": NEWS_SUMMARY_TASK_PROMPT,
        "prompt_news_relevance_system": NEWS_RELEVANCE_SYSTEM_PROMPT,
        "prompt_news_relevance_policy": NEWS_RELEVANCE_POLICY_PROMPT,
        "prompt_company_news_profile_system": COMPANY_NEWS_PROFILE_SYSTEM_PROMPT,
        "prompt_company_news_profile_requirements": COMPANY_NEWS_PROFILE_REQUIREMENTS_PROMPT,
        "prompt_final_judgement_user_instruction": FINAL_JUDGEMENT_USER_INSTRUCTION,
        "prompt_final_judgement_repair_instruction": FINAL_JUDGEMENT_REPAIR_INSTRUCTION,
        "disclosure_pdf_extract_on_update": DISCLOSURE_PDF_EXTRACT_ON_UPDATE,
        "disclosure_pdf_extract_limit": str(DISCLOSURE_PDF_EXTRACT_LIMIT),
        "disclosure_pdf_max_pages": str(DISCLOSURE_PDF_MAX_PAGES),
        "disclosure_pdf_ocr_enabled": DISCLOSURE_PDF_OCR_ENABLED,
        "update_schedule": "manual",
        "watchlist_default": "JPX400",
    }


def load_settings_file(fallback: dict[str, str] | None = None) -> dict[str, str]:
    fallback = fallback or default_app_settings()
    if not APP_SETTINGS_PATH.exists():
        save_settings_file(fallback)
        return dict(fallback)
    try:
        payload = json.loads(APP_SETTINGS_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid settings JSON: {APP_SETTINGS_PATH}") from exc
    raw_settings = payload.get("settings") if isinstance(payload, dict) and "settings" in payload else payload
    if not isinstance(raw_settings, dict):
        raise RuntimeError(f"Settings file must contain a JSON object: {APP_SETTINGS_PATH}")
    return {str(key): _setting_value(value) for key, value in raw_settings.items()}


def save_settings_file(settings: dict[str, str]) -> None:
    APP_SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
    normalized = {str(key): _setting_value(value) for key, value in sorted(settings.items())}
    tmp_path = APP_SETTINGS_PATH.with_suffix(APP_SETTINGS_PATH.suffix + ".tmp")
    tmp_path.write_text(json.dumps(normalized, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp_path.replace(APP_SETTINGS_PATH)


def current_settings(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["key"]: row["value"]
        for row in conn.execute("SELECT key, value FROM app_settings ORDER BY key ASC").fetchall()
    }


def upsert_setting(conn: sqlite3.Connection, key: str, value: str) -> dict[str, Any]:
    now = utc_now()
    conn.execute(
        """
        INSERT INTO app_settings (key, value, updated_at)
        VALUES (?, ?, ?)
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = excluded.updated_at
        """,
        (key, value, now),
    )
    settings = current_settings(conn)
    settings[key] = value
    save_settings_file(settings)
    row = conn.execute("SELECT key, value, updated_at FROM app_settings WHERE key = ?", (key,)).fetchone()
    return dict(row)


def _setting_value(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    return str(value)

SHORT_TERM_PROMPT = """あなたは日本株の中長期売買判断エンジンです。
入力はContext Packetのみです。Context Packetにない事実、比較、会社計画、業界平均、市場平均、アナリスト予想を作らないでください。
judgement_type/action/time_horizon/used_signal_types はJSON Schemaで指定された英字コードを使ってください。
それ以外の summary / positive_factors / negative_factors / entry_conditions / exit_conditions / risk_notes は日本語の自然文で書いてください。
説明文フィールドでは、英語の文章、英語の見出し、英語の箇条書きを使わないでください。
PER/PBR/ROE/EPS/配当利回りなど一般的な指標略語は使ってよいですが、説明は日本語にしてください。

判断対象:
- 3か月から1年程度の中長期判断
- BUY / WATCH_BUY / NO_TRADE / WATCH_SELL / SELL / INSUFFICIENT_DATA のいずれか
- リアルタイム株価ではなく、Context Packetのas_of時点の判断

必ず読む入力:
- company_profile: 会社の表記、主力/関連テーマ、業種、決算/会社概要、情報解釈ルール
- technical_summary: 価格・出来高・トレンドのSignal
- news_summary: LLMがタイトル重要度で選別した企業ニュース、適時開示、全体ニュースのSignal
- fundamental_summary: 財務指標、決算、業績予想、配当などのSignal
- aggregated_signal: 重み、総合スコア、情報源間の矛盾
- data_status: 欠損、鮮度、価格データ基準日
- signal_cards: 個別材料の方向、影響度、鮮度、根拠、リスク

判断方針:
- aggregated_signalは参考にするが、スコアだけで結論を決めない
- signal_cardsのimpact_score、freshness_score、confidenceが高い材料を優先する
- company_profileのbusiness_terms、sector、industry、financial_summaryを読み、この企業が何で稼ぐ企業かを前提に材料性を判断する
- 決算情報、PER/PBR/ROE/配当利回り等の指標、会社情報は必須の基礎情報として扱う
- 同じニュースでも、対象企業の主力事業・需要先・原材料・規制感応度に照らして、売上、利益率、受注、資本政策へどう効くかを判断する
- 良材料/悪材料を一般論で決めず、「この会社にとってなぜ良い/悪いのか」を説明できない場合は中立または要確認として扱う
- テクニカルだけで結論を出さず、news/fundamental/marketのSignalがあれば必ず判断理由かリスクに反映する
- テクニカルが弱くても、fundamentalのSignalが価値乖離や財務安全性を示す場合は、即売りではなくWATCH_BUYまたはNO_TRADEを検討する
- テクニカルが強くても、fundamental/news/marketに明確な悪材料がある場合はBUYを慎重にする
- conflict_levelがhighの場合は、BUY/SELLよりWATCH系またはNO_TRADEを優先する
- data_status.missing_dataがある場合はconfidenceを下げ、重大な欠損ならINSUFFICIENT_DATAを選ぶ
- 業績予想修正、上方修正、下方修正、増配、減配などは、signal_cardsのsummary/evidenceに明記されている場合だけ書く
- signal_cardsに「業績予想修正」だけがあり「上方修正」「下方修正」がない場合は、方向不明の業績予想修正として扱う

出力:
- JSON Schemaに従う
- judgement_typeはmid_long_termにする
- action/confidence/time_horizon/summary/positive_factors/negative_factors/entry_conditions/exit_conditions/risk_notesを必ず含める
- used_signal_typesを出す場合は、実際に使ったtechnical/news/fundamental/marketだけを入れる
- judgement_type/action/time_horizon/used_signal_types以外の説明文はすべて日本語で書く
- summaryには、会社の主力/関連テーマに照らした材料解釈と、使った主要Signalを2種類以上含める
- positive_factors/negative_factors/risk_notesは空にしない
- 投資助言として断定せず、条件付きの判断として書く
"""

NEWS_SUMMARY_SYSTEM_PROMPT = """あなたは日本株の情報圧縮担当です。
ニュース本文またはタイトルを、中長期投資判断で使える形へ要約してください。
company.business_profileには対象企業の主力/関連テーマ、業種、会社概要が含まれます。
記事の材料性は一般論ではなく、その企業の事業・需要先・原材料・規制感応度に照らして判断してください。
入力にない事実を作らず、本文が不足する場合はタイトルから分かる範囲だけを書いてください。
分類は必ずあなたが本文またはタイトルから判断し、RSSや取得元の内部カテゴリ名をそのまま使わないでください。
出力はJSONのみ、文字列は日本語にしてください。
"""

NEWS_SUMMARY_TASK_PROMPT = """中長期判断で使えるよう、分類、要約、要点、注意点、材料性を圧縮してください。
要約には「この企業のどの事業・収益要因に関係するか」を分かる範囲で含めてください。
本文が十分にある場合は本文を根拠にしてください。
本文がない場合はタイトルだけから分かることに限定し、断定を避けてください。
"""

NEWS_RELEVANCE_SYSTEM_PROMPT = """あなたは日本株の情報選別担当です。
本文は読まず、タイトルだけから、対象企業の中長期判断に重要な記事を選びます。
company.business_profileを読み、対象企業の主力事業・関連テーマ・業種に関係する記事を優先してください。
日次ランキングや汎用的な値動き記事は低評価です。
出力はJSONのみ、日本語で理由を書いてください。
"""

NEWS_RELEVANCE_POLICY_PROMPT = """決算、業績修正、配当、自社株買い、M&A、規制、事故、不正、訴訟、受注、設備投資を重視
全体ニュースでは金利、為替、原材料、関税、経済安全保障、地政学、当該企業の主力事業・業界への影響を重視
対象企業のbusiness_termsやindustryと結びつかない一般記事は低評価
単なるランキング、前日に動いた株、低PBR銘柄一覧、レーティング一覧は低評価
"""

COMPANY_NEWS_PROFILE_SYSTEM_PROMPT = """あなたは日本株ニュース収集の検索キーワード設計担当です。
対象企業に関係するニュースだけを保存するため、会社名表記、事業領域、重要材料語、除外語をJSONで返してください。
説明文は不要です。
"""

COMPANY_NEWS_PROFILE_REQUIREMENTS_PROMPT = """company_termsには正式名、略称、よく使われる表記を入れる
business_termsには主力事業、製品、需要先、関連テーマを入れる
material_termsには決算、受注、規制、M&Aなど投資判断に重要な語を入れる
exclude_termsにはランキング、一覧、定型コラムなど低価値記事の語を入れる
"""

FINAL_JUDGEMENT_USER_INSTRUCTION = """次のContext Packetだけを根拠に中長期売買判断を作成してください。
英字コード欄を除き、回答の説明文はすべて日本語にしてください。
会社名はContext Packetの表記を使い、英語社名を補完しないでください。
company_profileを必ず読み、この企業が何を主力にしているか、どの需要・原材料・規制・市況に影響を受けやすいかを前提にしてください。
良材料/悪材料は一般論ではなく、「この企業にとってなぜ良い/悪いのか」を説明できる場合だけ方向付けしてください。
fundamental_summaryには決算情報とPER/PBR/ROE等の指標が含まれます。必ず判断に使ってください。
news_summaryにはタイトル重要度で選別後に要約した企業ニュースと全体ニュースだけが含まれます。
signal_cardsにfundamental/news/marketが存在する場合は、summary、positive_factors、negative_factors、risk_notes のいずれかに必ず具体的に反映してください。
signal_cardsに業績予想修正だけがあり上方修正/下方修正がない場合は、方向不明の修正として扱ってください。
テクニカル指標だけで結論を出してはいけません。
judgement_typeは必ずmid_long_termにしてください。
必ず judgement_type/action/confidence/time_horizon/summary/positive_factors/negative_factors/entry_conditions/exit_conditions/risk_notes を含む判断JSONだけを返してください。
"""

FINAL_JUDGEMENT_REPAIR_INSTRUCTION = """前回の出力にはContext Packetにない事実または比較が含まれていました。
Context Packetに明記されていない業界平均、市場平均、上方修正、下方修正、業績予想修正、政策効果、景気回復などは削除してください。
signal_cardsのsummary/evidence/risk_notesとaggregated_signalだけに基づく日本語JSONを再出力してください。
英語文の混入がある場合は、summaryと各配列内の説明文を日本語へ書き換えてください。
judgement_type/action/time_horizon/used_signal_typesの英字コードはSchemaどおり残してください。
各配列には空文字ではなく、具体的な日本語文を入れてください。
data_status.missing_data が空の場合は、情報不足を主な結論にしないでください。
"""


def seed_default_prompt(conn: sqlite3.Connection) -> None:
    prompt_version = "v1.3"
    conn.execute(
        """
        INSERT INTO ai_prompt_templates
            (name, judgement_type, version, template_text, model_name, is_active, created_at)
        VALUES (?, ?, ?, ?, ?, 0, ?)
        ON CONFLICT(name, version) DO UPDATE SET
            template_text = excluded.template_text,
            model_name = excluded.model_name
        """,
        (
            "short_term_default",
            "short_term",
            prompt_version,
            SHORT_TERM_PROMPT,
            LLAMA_CPP_MODEL_NAME,
            utc_now(),
        ),
    )
    active = conn.execute(
        """
        SELECT id, name, version
        FROM ai_prompt_templates
        WHERE name = ? AND judgement_type = ? AND is_active = 1
        LIMIT 1
        """,
        ("short_term_default", "short_term"),
    ).fetchone()
    should_activate_default = active is None or (active["name"] == "short_term_default" and active["version"] != "custom")
    if should_activate_default:
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
            UPDATE ai_prompt_templates
            SET is_active = 1
            WHERE name = ? AND judgement_type = ? AND version = ?
            """,
            ("short_term_default", "short_term", prompt_version),
        )


def get_setting(conn: sqlite3.Connection, key: str, default: str | None = None) -> str | None:
    row = conn.execute("SELECT value FROM app_settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def get_active_prompt_template(conn: sqlite3.Connection, judgement_type: str = "short_term") -> dict[str, Any]:
    row = conn.execute(
        """
        SELECT *
        FROM ai_prompt_templates
        WHERE judgement_type = ? AND is_active = 1
        ORDER BY created_at DESC, id DESC
        LIMIT 1
        """,
        (judgement_type,),
    ).fetchone()
    if row is None:
        raise RuntimeError(f"Active {judgement_type} prompt template was not found")
    return dict(row)


def write_update_log(
    conn: sqlite3.Connection,
    *,
    job_name: str,
    status: str,
    source: str | None = None,
    message: str | None = None,
    metadata_json: str | None = None,
    started_at: str | None = None,
    finished_at: str | None = None,
) -> int:
    now = utc_now()
    cur = conn.execute(
        """
        INSERT INTO data_update_logs
            (job_name, source, status, started_at, finished_at, message, metadata_json)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            job_name,
            source,
            status,
            started_at or now,
            finished_at or now,
            message,
            metadata_json,
        ),
    )
    return int(cur.lastrowid)
