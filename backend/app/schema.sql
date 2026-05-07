PRAGMA journal_mode = WAL;
PRAGMA synchronous = NORMAL;
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    security_code TEXT NOT NULL UNIQUE,
    name TEXT NOT NULL,
    market TEXT,
    sector TEXT,
    industry TEXT,
    fiscal_year_end TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS price_bars (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    timeframe TEXT NOT NULL,
    date TEXT NOT NULL,
    open REAL,
    high REAL,
    low REAL,
    close REAL,
    volume REAL,
    adjusted_close REAL,
    source TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, timeframe, date, source)
);

CREATE INDEX IF NOT EXISTS idx_price_bars_company_timeframe_date
ON price_bars(company_id, timeframe, date);

CREATE TABLE IF NOT EXISTS technical_indicators (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    timeframe TEXT NOT NULL,
    date TEXT NOT NULL,

    ma_5 REAL,
    ma_25 REAL,
    ma_75 REAL,
    volume_ma_5 REAL,
    volume_ma_25 REAL,
    rsi_14 REAL,
    volatility_20 REAL,

    trend_short TEXT,
    trend_middle TEXT,
    recent_high_break INTEGER,
    recent_low_break INTEGER,
    gap_up INTEGER,
    gap_down INTEGER,

    features_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, timeframe, date)
);

CREATE INDEX IF NOT EXISTS idx_technical_indicators_company_timeframe_date
ON technical_indicators(company_id, timeframe, date);

CREATE TABLE IF NOT EXISTS watchlists (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    list_name TEXT NOT NULL DEFAULT 'default',
    memo TEXT,
    priority INTEGER NOT NULL DEFAULT 0,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, list_name)
);

CREATE TABLE IF NOT EXISTS disclosures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    title TEXT NOT NULL,
    document_type TEXT,
    published_at TEXT,
    information_date TEXT,
    source TEXT,
    url TEXT,
    local_path TEXT,
    summary TEXT,
    importance_score REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE INDEX IF NOT EXISTS idx_disclosures_company_published_at
ON disclosures(company_id, published_at);

CREATE TABLE IF NOT EXISTS company_financials (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    source TEXT NOT NULL,
    as_of TEXT NOT NULL,
    fiscal_period TEXT,
    next_earnings_date TEXT,
    summary TEXT,
    metrics_json TEXT,
    url TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, source, as_of)
);

CREATE INDEX IF NOT EXISTS idx_company_financials_company_as_of
ON company_financials(company_id, as_of);

CREATE TABLE IF NOT EXISTS news_articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT,
    information_date TEXT,
    source TEXT,
    provider TEXT,
    url TEXT,
    content_text TEXT,
    summary TEXT,
    relevance_score REAL,
    selection_reason TEXT,
    keyword_hits TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, source, url)
);

CREATE INDEX IF NOT EXISTS idx_news_articles_company_published_at
ON news_articles(company_id, published_at);

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
);

CREATE INDEX IF NOT EXISTS idx_company_news_profiles_company
ON company_news_profiles(company_id);

CREATE TABLE IF NOT EXISTS global_news (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT,
    information_date TEXT,
    source TEXT NOT NULL,
    provider TEXT,
    url TEXT,
    content_text TEXT,
    summary TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    UNIQUE(source, url)
);

CREATE INDEX IF NOT EXISTS idx_global_news_information_date
ON global_news(information_date);

CREATE TABLE IF NOT EXISTS external_factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    category TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT,
    information_date TEXT,
    source TEXT,
    provider TEXT,
    url TEXT,
    summary TEXT,
    relevance_score REAL,
    matched_keywords TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    UNIQUE(company_id, source, url)
);

CREATE INDEX IF NOT EXISTS idx_external_factors_company_published_at
ON external_factors(company_id, published_at);

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER,
    source TEXT NOT NULL,
    document_type TEXT NOT NULL,
    title TEXT NOT NULL,
    published_at TEXT,
    url TEXT,
    local_path TEXT,
    raw_text_path TEXT,
    extracted_text_status TEXT,
    metadata_json TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE TABLE IF NOT EXISTS ai_prompt_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    judgement_type TEXT NOT NULL,
    version TEXT NOT NULL,
    template_text TEXT NOT NULL,
    model_name TEXT,
    is_active INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,

    UNIQUE(name, version)
);

CREATE TABLE IF NOT EXISTS ai_judgements (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,
    judgement_type TEXT NOT NULL,
    target_date TEXT NOT NULL,

    action TEXT NOT NULL,
    confidence REAL,
    time_horizon TEXT,

    input_json TEXT NOT NULL,
    output_json TEXT NOT NULL,

    prompt_template_id INTEGER,
    model_provider TEXT NOT NULL DEFAULT 'llama_cpp',
    model_name TEXT,
    model_options_json TEXT,

    data_as_of TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id),
    FOREIGN KEY (prompt_template_id) REFERENCES ai_prompt_templates(id)
);

CREATE INDEX IF NOT EXISTS idx_ai_judgements_company_target_date
ON ai_judgements(company_id, target_date);

CREATE INDEX IF NOT EXISTS idx_ai_judgements_action
ON ai_judgements(action);

CREATE TABLE IF NOT EXISTS signal_cards (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL,

    source_type TEXT NOT NULL,
    source_id INTEGER,
    source_name TEXT,

    horizon TEXT NOT NULL,
    direction TEXT NOT NULL,
    direction_score REAL NOT NULL,
    impact_score REAL NOT NULL,
    confidence REAL NOT NULL,
    freshness_score REAL,
    relevance_score REAL,

    summary TEXT NOT NULL,
    evidence_json TEXT,
    risk_notes_json TEXT,

    valid_from TEXT,
    valid_until TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY (company_id) REFERENCES companies(id)
);

CREATE INDEX IF NOT EXISTS idx_signal_cards_company_horizon_created
ON signal_cards(company_id, horizon, created_at);

CREATE TABLE IF NOT EXISTS data_update_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_name TEXT NOT NULL,
    source TEXT,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    message TEXT,
    metadata_json TEXT
);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
