"""The items resource: schemas and routes."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from {{name_snake}}.store import Item, MemoryStore


class ItemIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    done: bool = False


class ItemOut(BaseModel):
    id: int
    name: str
    done: bool


def get_store(request: Request) -> MemoryStore:
    store: MemoryStore = request.app.state.store
    return store


Store = Annotated[MemoryStore, Depends(get_store)]
router = APIRouter(prefix="/api/items", tags=["items"])


def _out(item: Item) -> ItemOut:
    return ItemOut(id=item.id, name=item.name, done=item.done)


def _found(item: Item | None) -> Item:
    if item is None:
        raise HTTPException(404, "item not found")
    return item


@router.get("")
def list_items(store: Store) -> list[ItemOut]:
    return [_out(i) for i in store.list()]


@router.post("", status_code=201)
def create_item(body: ItemIn, store: Store) -> ItemOut:
    return _out(store.create(body.name.strip()))


@router.get("/{item_id}")
def get_item(item_id: int, store: Store) -> ItemOut:
    return _out(_found(store.get(item_id)))


@router.put("/{item_id}")
def update_item(item_id: int, body: ItemIn, store: Store) -> ItemOut:
    return _out(_found(store.update(item_id, body.name.strip(), body.done)))


@router.delete("/{item_id}", status_code=204)
def delete_item(item_id: int, store: Store) -> Response:
    if not store.delete(item_id):
        raise HTTPException(404, "item not found")
    return Response(status_code=204)
