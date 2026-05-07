from __future__ import annotations

from ..database import db_session
from ..services.information_dates import ensure_information_date_columns, refresh_information_dates


def main() -> None:
    with db_session() as conn:
        ensure_information_date_columns(conn)
        updated = refresh_information_dates(conn)
    print(f"Normalized information dates: {updated}")


if __name__ == "__main__":
    main()
