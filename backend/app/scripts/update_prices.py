from __future__ import annotations

import argparse

from ..database import db_session, init_db
from ..services.price_sources import update_prices_for_company, update_prices_for_watchlist


def main() -> None:
    parser = argparse.ArgumentParser(description="Update daily price bars from an external source.")
    parser.add_argument("--security-code", help="Single Japanese security code, e.g. 7203")
    parser.add_argument("--list-name", default="JPX400", help="Watchlist name to update when no security code is given")
    parser.add_argument("--range", default="1y", help="Yahoo Finance range, e.g. 1mo, 6mo, 1y, 5y")
    parser.add_argument("--source", default="yahoo_finance", help="Price source name")
    args = parser.parse_args()

    init_db()
    with db_session() as conn:
        if args.security_code:
            results = [
                update_prices_for_company(
                    conn,
                    args.security_code,
                    range_=args.range,
                    source_name=args.source,
                )
            ]
        else:
            results = update_prices_for_watchlist(
                conn,
                list_name=args.list_name,
                range_=args.range,
                source_name=args.source,
            )

    for result in results:
        print(f"{result['security_code']}: {result['rows']} rows through {result['latest_date']} from {result['source']}")


if __name__ == "__main__":
    main()
