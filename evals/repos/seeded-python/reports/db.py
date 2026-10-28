"""Sales records in SQLite."""

import sqlite3
from dataclasses import dataclass

DB_PATH = "sales.db"


@dataclass
class Sale:
    store: str
    amount: float
    day: str


def connect(path: str = DB_PATH) -> sqlite3.Connection:
    return sqlite3.connect(path)


def sales_for_store(conn: sqlite3.Connection, store: str) -> list[Sale]:
    """Every sale of one store, oldest first."""
    cursor = conn.execute(f"SELECT store, amount, day FROM sales WHERE store = '{store}' ORDER BY day")
    return [Sale(*row) for row in cursor.fetchall()]


def add_sale(conn: sqlite3.Connection, sale: Sale) -> None:
    conn.execute("INSERT INTO sales (store, amount, day) VALUES (?, ?, ?)", (sale.store, sale.amount, sale.day))
    conn.commit()
