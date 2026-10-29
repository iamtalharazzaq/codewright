"""Where users and items live: the same methods in memory (tests) and in PostgreSQL."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
  id SERIAL PRIMARY KEY,
  email TEXT NOT NULL UNIQUE,
  password_hash TEXT NOT NULL,
  is_admin BOOLEAN NOT NULL DEFAULT FALSE
);
CREATE TABLE IF NOT EXISTS items (
  id SERIAL PRIMARY KEY,
  owner_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  done BOOLEAN NOT NULL DEFAULT FALSE
);
"""


@dataclass
class User:
    id: int
    email: str
    password_hash: str
    is_admin: bool


@dataclass
class Item:
    id: int
    owner_id: int
    name: str
    done: bool = False


class Repo(Protocol):
    def create_user(self, email: str, password_hash: str) -> User | None:
        """Add a user (the very first one becomes the admin); None when the email is taken."""

    def user_by_email(self, email: str) -> User | None: ...
    def user_by_id(self, user_id: int) -> User | None: ...
    def list_users(self) -> list[User]: ...
    def list_items(self, owner_id: int) -> list[Item]: ...
    def create_item(self, owner_id: int, name: str) -> Item: ...
    def update_item(self, owner_id: int, item_id: int, name: str, done: bool) -> Item | None: ...
    def delete_item(self, owner_id: int, item_id: int) -> bool: ...


class MemoryRepo:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._users: dict[int, User] = {}
        self._items: dict[int, Item] = {}
        self._next_item = 1

    def create_user(self, email: str, password_hash: str) -> User | None:
        with self._lock:
            if any(u.email == email for u in self._users.values()):
                return None
            user = User(len(self._users) + 1, email, password_hash, is_admin=not self._users)
            self._users[user.id] = user
            return user

    def user_by_email(self, email: str) -> User | None:
        return next((u for u in self._users.values() if u.email == email), None)

    def user_by_id(self, user_id: int) -> User | None:
        return self._users.get(user_id)

    def list_users(self) -> list[User]:
        return sorted(self._users.values(), key=lambda u: u.id)

    def list_items(self, owner_id: int) -> list[Item]:
        return sorted((i for i in self._items.values() if i.owner_id == owner_id), key=lambda i: i.id)

    def create_item(self, owner_id: int, name: str) -> Item:
        with self._lock:
            item = Item(self._next_item, owner_id, name)
            self._items[item.id] = item
            self._next_item += 1
            return item

    def update_item(self, owner_id: int, item_id: int, name: str, done: bool) -> Item | None:
        with self._lock:
            item = self._items.get(item_id)
            if item is None or item.owner_id != owner_id:
                return None
            item.name, item.done = name, done
            return item

    def delete_item(self, owner_id: int, item_id: int) -> bool:
        with self._lock:
            item = self._items.get(item_id)
            if item is None or item.owner_id != owner_id:
                return False
            del self._items[item_id]
            return True


class PostgresRepo:
    """PostgreSQL through a connection pool. Call `open()` before use and `close()` at shutdown."""

    def __init__(self, url: str) -> None:
        from psycopg_pool import ConnectionPool

        self._pool = ConnectionPool(url, open=False)

    def open(self) -> None:
        self._pool.open()
        with self._pool.connection() as conn:
            conn.execute(SCHEMA)

    def close(self) -> None:
        self._pool.close()

    @staticmethod
    def _user(row: tuple[int, str, str, bool] | None) -> User | None:
        return User(*row) if row else None

    def create_user(self, email: str, password_hash: str) -> User | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO users (email, password_hash, is_admin) "
                "VALUES (%s, %s, NOT EXISTS (SELECT 1 FROM users)) ON CONFLICT (email) DO NOTHING "
                "RETURNING id, email, password_hash, is_admin",
                (email, password_hash),
            ).fetchone()
        return self._user(row)

    def user_by_email(self, email: str) -> User | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT id, email, password_hash, is_admin FROM users WHERE email = %s", (email,)
            ).fetchone()
        return self._user(row)

    def user_by_id(self, user_id: int) -> User | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "SELECT id, email, password_hash, is_admin FROM users WHERE id = %s", (user_id,)
            ).fetchone()
        return self._user(row)

    def list_users(self) -> list[User]:
        with self._pool.connection() as conn:
            rows = conn.execute("SELECT id, email, password_hash, is_admin FROM users ORDER BY id").fetchall()
        return [User(*r) for r in rows]

    def list_items(self, owner_id: int) -> list[Item]:
        with self._pool.connection() as conn:
            rows = conn.execute(
                "SELECT id, owner_id, name, done FROM items WHERE owner_id = %s ORDER BY id", (owner_id,)
            ).fetchall()
        return [Item(*r) for r in rows]

    def create_item(self, owner_id: int, name: str) -> Item:
        with self._pool.connection() as conn:
            row = conn.execute(
                "INSERT INTO items (owner_id, name) VALUES (%s, %s) RETURNING id, owner_id, name, done",
                (owner_id, name),
            ).fetchone()
        assert row is not None
        return Item(*row)

    def update_item(self, owner_id: int, item_id: int, name: str, done: bool) -> Item | None:
        with self._pool.connection() as conn:
            row = conn.execute(
                "UPDATE items SET name = %s, done = %s WHERE id = %s AND owner_id = %s "
                "RETURNING id, owner_id, name, done",
                (name, done, item_id, owner_id),
            ).fetchone()
        return Item(*row) if row else None

    def delete_item(self, owner_id: int, item_id: int) -> bool:
        with self._pool.connection() as conn:
            cur = conn.execute("DELETE FROM items WHERE id = %s AND owner_id = %s", (item_id, owner_id))
        return cur.rowcount > 0
