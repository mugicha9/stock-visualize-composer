from __future__ import annotations

from ..database import db_session, init_db
from ..services.price_sources import delete_test_data


def main() -> None:
    init_db()
    with db_session() as conn:
        deleted = delete_test_data(conn)
    for key, value in deleted.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
