export type Action =
  | "BUY"
  | "WATCH_BUY"
  | "NO_TRADE"
  | "WATCH_SELL"
  | "SELL"
  | "INSUFFICIENT_DATA";

export type Company = {
  id: number;
  security_code: string;
  name: string;
  market?: string | null;
  sector?: string | null;
  industry?: string | null;
  latest_price?: PriceBar | null;
  latest_indicator?: TechnicalIndicator | null;
};

export type PriceBar = {
  date: string;
  open: number | null;
  high: number | null;
  low: number | null;
  close: number | null;
  volume: number | null;
  adjusted_close?: number | null;
  source?: string | null;
};

export type TechnicalFeatures = {
  last_close?: number | null;
  change_1d_pct?: number | null;
  change_5d_pct?: number | null;
  change_20d_pct?: number | null;
  ma_5?: number | null;
  ma_25?: number | null;
  ma_75?: number | null;
  price_vs_ma_5_pct?: number | null;
  price_vs_ma_25_pct?: number | null;
  price_vs_ma_75_pct?: number | null;
  volume_ratio_5d?: number | null;
  volatility_20d?: number | null;
  trend_short?: string | null;
  trend_middle?: string | null;
  recent_high_break?: boolean | null;
  recent_low_break?: boolean | null;
  gap_up?: boolean | null;
  gap_down?: boolean | null;
};

export type TechnicalIndicator = {
  date: string;
  ma_5?: number | null;
  ma_25?: number | null;
  ma_75?: number | null;
  volume_ma_5?: number | null;
  volume_ma_25?: number | null;
  trend_short?: string | null;
  trend_middle?: string | null;
  features?: TechnicalFeatures;
};

export type JudgementOutput = {
  judgement_type: "mid_long_term";
  action: Action;
  confidence: number;
  time_horizon: string;
  summary: string;
  positive_factors: string[];
  negative_factors: string[];
  entry_conditions: string[];
  exit_conditions: string[];
  risk_notes: string[];
  used_signal_ids?: string[];
  used_signal_types?: Array<"technical" | "news" | "fundamental" | "market">;
};

export type Judgement = {
  id: number;
  security_code?: string;
  company_name?: string;
  target_date: string;
  action: Action;
  confidence: number;
  model_provider: string;
  model_name?: string | null;
  created_at: string;
  output?: JudgementOutput;
  input?: Record<string, unknown> | null;
  model_options?: Record<string, unknown> | null;
};

export type SignalSourceType = "technical" | "news" | "fundamental" | "market";
export type SignalDirection = "bullish" | "bearish" | "neutral";

export type SignalCard = {
  signal_id: string;
  company_code?: string;
  source_type: SignalSourceType | string;
  source_name?: string | null;
  published_at?: string | null;
  horizon?: string | null;
  direction: SignalDirection | string;
  direction_score: number;
  impact_score: number;
  confidence: number;
  freshness_score: number;
  relevance_score?: number | null;
  summary: string;
  evidence?: string[];
  risk_notes?: string[];
  category?: string | null;
  topic?: string | null;
  title?: string | null;
  db_id?: number | null;
  used_by_judgement?: boolean | null;
  material_assessment?: {
    provider?: string;
    direction?: string;
    direction_score?: number;
    impact_score?: number;
    confidence?: number;
    company_relevance?: number;
    expectation_gap?: string;
    reason?: string;
    risk_notes?: string[];
    used_evidence?: string[];
  } | null;
};

export type ContextSummaryBlock = {
  direction_score: number;
  impact_score: number;
  summary: string;
  top_signals?: SignalCard[];
  risk_notes?: string[];
};

export type ContextPacket = {
  company?: Partial<Company>;
  company_profile?: {
    company_terms?: string[];
    business_terms?: string[];
    material_terms?: string[];
    exclude_terms?: string[];
    sector?: string | null;
    industry?: string | null;
    financial_summary?: string | null;
    interpretation_rule?: string | null;
    profile_source?: string | null;
  };
  as_of?: string | null;
  judgement_type?: "mid_long_term";
  time_horizon?: string;
  data_status?: {
    price_data_as_of?: string | null;
    price_data_age_days?: number | null;
    fundamental_data_as_of?: string | null;
    news_counts?: Record<string, number>;
    has_stale_data?: boolean;
    missing_data?: string[];
  };
  technical_summary?: ContextSummaryBlock;
  news_summary?: ContextSummaryBlock;
  fundamental_summary?: ContextSummaryBlock;
  aggregated_signal?: {
    technical_score?: number;
    news_score?: number;
    fundamental_score?: number;
    weights?: Record<string, number>;
    weighted_score?: number;
    conflict_level?: string;
    overall_bias?: string;
    signal_count?: number;
  };
  signal_cards?: SignalCard[];
};

export type JudgementSourceItem = {
  id?: number;
  type?: string;
  date?: string | null;
  published_at?: string | null;
  information_date?: string | null;
  source?: string | null;
  provider?: string | null;
  category?: string | null;
  title?: string | null;
  summary?: string | null;
  url?: string | null;
  importance_score?: number | null;
  relevance_score?: number | null;
  selection_reason?: string | null;
};

export type JudgementContext = {
  judgement: Judgement;
  context_packet: ContextPacket;
  card_counts: Record<string, number>;
  source_items: {
    news_digest_items: JudgementSourceItem[];
    financial_disclosures: JudgementSourceItem[];
    recent_news_candidates: JudgementSourceItem[];
    recent_disclosures: JudgementSourceItem[];
    selected_global_news: JudgementSourceItem[];
  };
  generated_from_saved_input: boolean;
  loaded_from_context_packet?: boolean;
};

export type Disclosure = {
  id: number;
  title: string;
  document_type?: string | null;
  published_at?: string | null;
  source?: string | null;
  url?: string | null;
  summary?: string | null;
  importance_score?: number | null;
};

export type FinancialMetric = {
  name: string;
  value: string | number;
  suffix?: string | null;
  update_date?: string | null;
  update_date_meta?: string | null;
};

export type FinancialSnapshot = {
  id: number;
  source: string;
  as_of: string;
  fiscal_period?: string | null;
  next_earnings_date?: string | null;
  summary?: string | null;
  metrics?: Record<string, FinancialMetric> | null;
  url?: string | null;
};

export type NewsArticle = {
  id: number;
  title: string;
  published_at?: string | null;
  information_date?: string | null;
  source?: string | null;
  provider?: string | null;
  url?: string | null;
  content_text?: string | null;
  summary?: string | null;
  relevance_score?: number | null;
  selection_reason?: string | null;
  keyword_hits?: string | null;
};

export type GlobalNews = {
  id: number;
  category: string;
  title: string;
  published_at?: string | null;
  information_date?: string | null;
  source?: string | null;
  provider?: string | null;
  url?: string | null;
  content_text?: string | null;
  summary?: string | null;
};

export type ExternalFactor = GlobalNews & {
  relevance_score?: number | null;
  matched_keywords?: string | null;
};

export type ExternalAdvicePrompt = {
  security_code: string;
  company_name: string;
  prompt_template_version: string;
  prompt: string;
  input: Record<string, unknown>;
};

export type WatchlistItem = Company & {
  watchlist_id: number;
  list_name: string;
  memo?: string | null;
  priority: number;
  latest_judgement?: Judgement | null;
  latest_disclosure?: Disclosure | null;
};

export type ChartBar = PriceBar & {
  ma_5?: number | null;
  ma_25?: number | null;
  ma_75?: number | null;
  volume_ma_5?: number | null;
  volume_ma_25?: number | null;
};

export type ChartResponse = {
  company: Company;
  timeframe: string;
  bars: ChartBar[];
};

export type BacktestInterval = "1d" | "1w" | "2w" | "1mo";
export type BacktestProvider = "mock" | "llama_cpp";

export type BacktestRequest = {
  security_code: string;
  start_date?: string | null;
  end_date?: string | null;
  interval: BacktestInterval;
  provider: BacktestProvider;
  model_name?: string | null;
  max_steps?: number;
};

export type BacktestDecision = {
  date: string;
  price_close?: number | null;
  action: Action;
  confidence: number;
  summary: string;
  data_as_of: string;
  data_counts: Record<string, number>;
  data_warnings: string[];
  next_execution_date: string;
  next_execution_price?: number | null;
  executed_action?: "BUY" | "SELL" | null;
  position_after: "long" | "flat";
  equity_pct: number;
};

export type BacktestTrade = {
  entry_date: string;
  entry_price: number;
  entry_signal_date: string;
  entry_signal: Action;
  exit_date: string;
  exit_price: number;
  exit_signal_date: string;
  exit_signal: Action;
  exit_reason: string;
  return_pct: number;
};

export type BacktestEquityPoint = {
  date: string;
  normalized_value: number;
  return_pct: number;
};

export type BacktestResponse = {
  company: Company;
  config: {
    start_date: string;
    end_date: string;
    requested_start_date: string;
    requested_end_date: string;
    interval: BacktestInterval;
    provider: BacktestProvider;
    model_name?: string | null;
    execution_policy: string;
    max_steps: number;
    truncated: boolean;
  };
  summary: {
    total_return_pct: number;
    buy_and_hold_return_pct?: number | null;
    excess_return_pct?: number | null;
    trade_count: number;
    win_rate_pct?: number | null;
    average_trade_return_pct?: number | null;
    max_drawdown_pct: number;
  };
  decisions: BacktestDecision[];
  trades: BacktestTrade[];
  equity_curve: BacktestEquityPoint[];
  errors: Array<{ date: string; message: string }>;
  leakage_guard: Record<string, string>;
};

export type BacktestPeriodInfoRequest = {
  security_code: string;
  start_date?: string | null;
  end_date?: string | null;
  persist: boolean;
  include_news?: boolean;
  include_disclosures?: boolean;
  include_external_factors?: boolean;
  news_limit?: number;
  disclosure_limit?: number;
  external_factor_limit?: number;
};

export type BacktestPeriodCoverage = {
  available: number;
  earliest_date?: string | null;
  latest_date?: string | null;
  missing_information_date: number;
};

export type BacktestPeriodInfoResponse = {
  company: Pick<Company, "id" | "security_code" | "name">;
  period: {
    start_date: string;
    end_date: string;
  };
  persisted: boolean;
  requested: {
    include_news: boolean;
    include_disclosures: boolean;
    include_external_factors: boolean;
  };
  fetched: Record<string, unknown>;
  coverage_before: Record<string, BacktestPeriodCoverage>;
  coverage_after: Record<string, BacktestPeriodCoverage>;
  source_notes: string[];
};
