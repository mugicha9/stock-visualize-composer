from __future__ import annotations

import json

from ..database import db_session, utc_now, write_update_log


VOLATILE_TABLES = [
    "judgement_signal_links",
    "signal_cards",
    "ai_judgements",
    "context_packets",
    "event_summaries",
    "event_triage",
    "source_events",
    "technical_indicators",
    "price_bars",
    "disclosures",
    "company_financials",
    "news_articles",
    "global_news",
    "external_factors",
    "documents",
    "data_update_logs",
]


def reset_market_data() -> dict[str, int]:
    started_at = utc_now()
    deleted: dict[str, int] = {}
    with db_session() as conn:
        for table in VOLATILE_TABLES:
            deleted[table] = conn.execute(f"DELETE FROM {table}").rowcount
        write_update_log(
            conn,
            job_name="reset_market_data",
            source="sqlite",
            status="success",
            message="Cleared volatile market data; companies, watchlists, settings, and prompts were kept",
            metadata_json=json.dumps(deleted, ensure_ascii=False),
            started_at=started_at,
            finished_at=utc_now(),
        )
    return deleted


def main() -> None:
    deleted = reset_market_data()
    print(json.dumps(deleted, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
