from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


Action = Literal[
    "BUY",
    "WATCH_BUY",
    "NO_TRADE",
    "WATCH_SELL",
    "SELL",
    "INSUFFICIENT_DATA",
]
Provider = Literal["mock", "llama_cpp"]


class CompanyCreate(BaseModel):
    security_code: str = Field(min_length=4, max_length=5)
    name: str | None = None
    market: str | None = None
    sector: str | None = None
    industry: str | None = None


class WatchlistCreate(BaseModel):
    security_code: str = Field(min_length=4, max_length=5)
    name: str | None = None
    list_name: str = "JPX400"
    memo: str | None = None
    priority: int = 0
    fetch_prices: bool = False
    fetch_context: bool = False
    summarize_news: bool = False
    price_range: str = "1y"


class DisclosureCreate(BaseModel):
    title: str
    document_type: str | None = None
    published_at: str | None = None
    source: str | None = "manual"
    url: str | None = None
    summary: str | None = None
    importance_score: float | None = None


class RunJudgementRequest(BaseModel):
    provider: Provider | None = None
    model_name: str | None = None


class FetchCompanyDataRequest(BaseModel):
    price_range: str = "1y"
    include_prices: bool = True
    include_financials: bool = True
    include_disclosures: bool = True
    include_news: bool = True
    summarize_news: bool = False
    include_external_factors: bool = False


class JudgementOutput(BaseModel):
    judgement_type: Literal["mid_long_term"]
    action: Action
    confidence: float = Field(ge=0, le=1)
    time_horizon: str
    summary: str
    positive_factors: list[str]
    negative_factors: list[str]
    entry_conditions: list[str]
    exit_conditions: list[str]
    risk_notes: list[str]


class JobRequest(BaseModel):
    security_code: str | None = None
    provider: Provider | None = None
    list_name: str | None = None
    range: str = "1y"
    source: str = "yahoo_finance"


class BacktestRequest(BaseModel):
    security_code: str = Field(min_length=4, max_length=5)
    start_date: str | None = None
    end_date: str | None = None
    interval: Literal["1d", "1w", "2w", "1mo"] = "1mo"
    provider: Provider = "mock"
    model_name: str | None = None
    max_steps: int = Field(default=260, ge=1, le=520)


class BacktestPeriodInfoRequest(BaseModel):
    security_code: str = Field(min_length=4, max_length=5)
    start_date: str | None = None
    end_date: str | None = None
    persist: bool = True
    include_news: bool = True
    include_disclosures: bool = True
    include_external_factors: bool = True
    news_limit: int = Field(default=80, ge=1, le=200)
    disclosure_limit: int = Field(default=80, ge=1, le=200)
    external_factor_limit: int = Field(default=80, ge=1, le=200)


class ApiError(BaseModel):
    detail: str | dict[str, Any]
