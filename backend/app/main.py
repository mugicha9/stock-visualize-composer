from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import CORS_ORIGINS
from .database import init_db
from .routers import ai_judgements, backtests, companies, disclosures, jobs, market_news, prompts, settings, watchlist


@asynccontextmanager
async def lifespan(app: FastAPI):
    del app
    init_db()
    yield


app = FastAPI(
    title="Stock Visualize Composer API",
    version="0.1.0",
    description="Japanese stock short-term decision support API for local use.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(companies.router)
app.include_router(watchlist.router)
app.include_router(disclosures.router)
app.include_router(ai_judgements.router)
app.include_router(backtests.router)
app.include_router(jobs.router)
app.include_router(market_news.router)
app.include_router(settings.router)
app.include_router(prompts.router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
