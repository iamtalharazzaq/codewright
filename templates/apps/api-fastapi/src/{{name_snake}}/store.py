"""Where items live. Swap `MemoryStore` for a database-backed class with the same methods."""

from __future__ import annotations

import threading
from dataclasses import dataclass


@dataclass
class Item:
    id: int
    name: str
    done: bool = False


class MemoryStore:
    """A store in memory, safe for concurrent use."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._next = 1
        self._items: dict[int, Item] = {}

    def list(self) -> list[Item]:
        with self._lock:
            return sorted(self._items.values(), key=lambda i: i.id)

    def get(self, item_id: int) -> Item | None:
        with self._lock:
            return self._items.get(item_id)

    def create(self, name: str) -> Item:
        with self._lock:
            item = Item(self._next, name)
            self._items[item.id] = item
            self._next += 1
            return item

    def update(self, item_id: int, name: str, done: bool) -> Item | None:
        with self._lock:
            if item_id not in self._items:
                return None
            item = Item(item_id, name, done)
            self._items[item_id] = item
            return item

    def delete(self, item_id: int) -> bool:
        with self._lock:
            return self._items.pop(item_id, None) is not None
