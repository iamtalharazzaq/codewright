"""The API: sign-up and sign-in, the signed-in user's items, and an admin-only user list."""

from __future__ import annotations

import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field

from app.repo import Item, MemoryRepo, PostgresRepo, Repo, User
from app.security import hash_password, make_token, read_token, verify_password

log = logging.getLogger("app")
SECRET = os.environ.get("SECRET_KEY", "dev-secret-change-me")
if SECRET == "dev-secret-change-me":
    log.warning("SECRET_KEY is not set: using an insecure development secret")


@asynccontextmanager
async def lifespan(application: FastAPI) -> AsyncIterator[None]:
    repo = application.state.repo
    if isinstance(repo, PostgresRepo):
        repo.open()
    yield
    if isinstance(repo, PostgresRepo):
        repo.close()


app = FastAPI(title="{{title}}", description="{{description}}", lifespan=lifespan)
url = os.environ.get("DATABASE_URL")
app.state.repo = PostgresRepo(url) if url else MemoryRepo()  # no DATABASE_URL: in memory, handy for trying it out


class Credentials(BaseModel):
    email: Annotated[str, Field(min_length=3, max_length=254, pattern=r"^[^@\s]+@[^@\s]+$")]
    password: Annotated[str, Field(min_length=8, max_length=200)]


class ItemIn(BaseModel):
    name: Annotated[str, Field(min_length=1, max_length=200)]
    done: bool = False


def get_repo(request: Request) -> Repo:
    repo: Repo = request.app.state.repo
    return repo


def public(user: User) -> dict[str, object]:
    return {"id": user.id, "email": user.email, "is_admin": user.is_admin}


def current_user(repo: Annotated[Repo, Depends(get_repo)], authorization: Annotated[str | None, Header()] = None) -> User:
    scheme, _, token = (authorization or "").partition(" ")
    user_id = read_token(SECRET, token) if scheme.lower() == "bearer" else None
    user = repo.user_by_id(user_id) if user_id else None
    if user is None:
        raise HTTPException(401, "sign in first")
    return user


def admin_user(user: Annotated[User, Depends(current_user)]) -> User:
    if not user.is_admin:
        raise HTTPException(403, "admins only")
    return user


def item_json(item: Item) -> dict[str, object]:
    return {"id": item.id, "name": item.name, "done": item.done}


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/api/auth/register", status_code=201)
def register(body: Credentials, repo: Annotated[Repo, Depends(get_repo)]) -> dict[str, object]:
    user = repo.create_user(body.email.lower(), hash_password(body.password))
    if user is None:
        raise HTTPException(409, "that email is already registered")
    return {"token": make_token(SECRET, user.id), "user": public(user)}


@app.post("/api/auth/login")
def login(body: Credentials, repo: Annotated[Repo, Depends(get_repo)]) -> dict[str, object]:
    user = repo.user_by_email(body.email.lower())
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(401, "wrong email or password")
    return {"token": make_token(SECRET, user.id), "user": public(user)}


@app.get("/api/me")
def me(user: Annotated[User, Depends(current_user)]) -> dict[str, object]:
    return public(user)


@app.get("/api/items")
def list_items(user: Annotated[User, Depends(current_user)], repo: Annotated[Repo, Depends(get_repo)]) -> list[dict[str, object]]:
    return [item_json(i) for i in repo.list_items(user.id)]


@app.post("/api/items", status_code=201)
def create_item(body: ItemIn, user: Annotated[User, Depends(current_user)], repo: Annotated[Repo, Depends(get_repo)]) -> dict[str, object]:
    return item_json(repo.create_item(user.id, body.name.strip()))


@app.put("/api/items/{item_id}")
def update_item(item_id: int, body: ItemIn, user: Annotated[User, Depends(current_user)], repo: Annotated[Repo, Depends(get_repo)]) -> dict[str, object]:
    item = repo.update_item(user.id, item_id, body.name.strip(), body.done)
    if item is None:
        raise HTTPException(404, "item not found")
    return item_json(item)


@app.delete("/api/items/{item_id}", status_code=204)
def delete_item(item_id: int, user: Annotated[User, Depends(current_user)], repo: Annotated[Repo, Depends(get_repo)]) -> Response:
    if not repo.delete_item(user.id, item_id):
        raise HTTPException(404, "item not found")
    return Response(status_code=204)


@app.get("/api/admin/users")
def list_users(_: Annotated[User, Depends(admin_user)], repo: Annotated[Repo, Depends(get_repo)]) -> list[dict[str, object]]:
    return [public(u) for u in repo.list_users()]
