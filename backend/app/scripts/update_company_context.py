from __future__ import annotations

import argparse
import json

from ..database import db_session, get_setting
from ..services.company_sources import (
    update_disclosures_for_company,
    update_financials_for_company,
    update_news_for_company,
)
from ..services.global_news import update_global_news
from ..services.price_sources import update_prices_for_company


def main() -> None:
    parser = argparse.ArgumentParser(description="Update prices, company financials, disclosures, company news, and shared global news.")
    parser.add_argument("--security-code")
    parser.add_argument("--list-name")
    parser.add_argument("--range", default="1y")
    parser.add_argument("--skip-prices", action="store_true")
    parser.add_argument("--skip-context", action="store_true")
    args = parser.parse_args()

    with db_session() as conn:
        codes = [args.security_code] if args.security_code else _watchlist_codes(conn, args.list_name)
        if not args.skip_context:
            global_limit = int(get_setting(conn, "global_news_fetch_limit_per_source", "40") or "40")
            print(json.dumps({"global_news": update_global_news(conn, limit_per_source=global_limit)}, ensure_ascii=False))
        for code in codes:
            result: dict[str, object] = {"security_code": code}
            if not args.skip_prices:
                result["prices"] = update_prices_for_company(conn, code, range_=args.range)
            if not args.skip_context:
                result["financials"] = update_financials_for_company(conn, code)
                result["disclosures"] = len(update_disclosures_for_company(conn, code))
                result["news"] = len(update_news_for_company(conn, code))
            print(json.dumps(result, ensure_ascii=False))


def _watchlist_codes(conn, list_name: str | None) -> list[str]:
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
    return [row["security_code"] for row in rows]


if __name__ == "__main__":
    main()
