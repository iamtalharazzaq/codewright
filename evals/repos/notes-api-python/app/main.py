"""Notes API: register, log in, and keep notes with tags."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, HTTPException, Response
from pydantic import BaseModel, EmailStr, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth import check_password, current_user, hash_password, make_token
from app.db import Base, Note, User, engine, get_session

SessionDep = Annotated[Session, Depends(get_session)]
UserDep = Annotated[User, Depends(current_user)]


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="Notes API", lifespan=lifespan)
auth = APIRouter(prefix="/auth", tags=["auth"])
notes = APIRouter(prefix="/notes", tags=["notes"])


class RegisterIn(BaseModel):
    email: EmailStr
    name: str = Field(min_length=1, max_length=100)
    password: str = Field(min_length=8)


class LoginIn(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: str
    email: str
    name: str
    created_at: datetime


class NoteIn(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    body: str = ""
    tags: list[str] = []


class NotePatch(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=200)
    body: str | None = None
    tags: list[str] | None = None


class NoteOut(BaseModel):
    id: str
    title: str
    body: str
    tags: list[str]
    created_at: datetime
    updated_at: datetime


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@auth.post("/register", status_code=201)
def register(body: RegisterIn, session: SessionDep) -> UserOut:
    if session.scalar(select(User).where(User.email == body.email.lower())):
        raise HTTPException(409, "That email is already registered")
    user = User(email=body.email.lower(), name=body.name, password_hash=hash_password(body.password))
    session.add(user)
    session.commit()
    return UserOut.model_validate(user, from_attributes=True)


@auth.post("/login")
def login(body: LoginIn, session: SessionDep) -> dict[str, str]:
    user = session.scalar(select(User).where(User.email == body.email.lower()))
    if user is None or not check_password(body.password, user.password_hash):
        raise HTTPException(401, "Wrong email or password")
    return {"access_token": make_token(user), "token_type": "bearer"}


@auth.get("/me")
def me(user: UserDep) -> UserOut:
    return UserOut.model_validate(user, from_attributes=True)


def _own(session: Session, user: User, note_id: str) -> Note:
    note = session.get(Note, note_id)
    if note is None or note.owner_id != user.id:
        raise HTTPException(404, "Note not found")
    return note


@notes.get("")
def list_notes(user: UserDep, session: SessionDep, tag: str | None = None) -> list[NoteOut]:
    rows = session.scalars(select(Note).where(Note.owner_id == user.id).order_by(Note.created_at, Note.title))
    return [NoteOut.model_validate(n, from_attributes=True) for n in rows if tag is None or tag in n.tags]


@notes.post("", status_code=201)
def create_note(body: NoteIn, user: UserDep, session: SessionDep) -> NoteOut:
    note = Note(owner_id=user.id, title=body.title, body=body.body, tags=sorted(set(body.tags)))
    session.add(note)
    session.commit()
    return NoteOut.model_validate(note, from_attributes=True)


@notes.get("/{note_id}")
def get_note(note_id: str, user: UserDep, session: SessionDep) -> NoteOut:
    return NoteOut.model_validate(_own(session, user, note_id), from_attributes=True)


@notes.patch("/{note_id}")
def update_note(note_id: str, body: NotePatch, user: UserDep, session: SessionDep) -> NoteOut:
    note = _own(session, user, note_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(note, field, sorted(set(value)) if field == "tags" else value)
    session.commit()
    return NoteOut.model_validate(note, from_attributes=True)


@notes.delete("/{note_id}", status_code=204)
def delete_note(note_id: str, user: UserDep, session: SessionDep) -> Response:
    session.delete(_own(session, user, note_id))
    session.commit()
    return Response(status_code=204)


@notes.get("/stats/summary")
def stats(user: UserDep, session: SessionDep) -> dict[str, object]:
    rows = list(session.scalars(select(Note).where(Note.owner_id == user.id)))
    words = [len(n.body.split()) for n in rows]
    tags: dict[str, int] = {}
    for n in rows:
        for t in n.tags:
            tags[t] = tags.get(t, 0) + 1
    return {"notes": len(rows), "average_words": sum(words) / len(words) if words else 0.0, "tags": tags}


app.include_router(auth, prefix="/api")
app.include_router(notes, prefix="/api")
