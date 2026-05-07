from __future__ import annotations

import sqlite3
from collections.abc import Generator

from .database import connect_db


def get_db() -> Generator[sqlite3.Connection, None, None]:
    conn = connect_db()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

