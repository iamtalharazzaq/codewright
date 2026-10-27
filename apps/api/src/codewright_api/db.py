"""Database engine, session dependency and ORM models (async SQLAlchemy on psycopg 3)."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from datetime import datetime
from functools import lru_cache
from typing import Annotated, Any, ClassVar

from fastapi import Depends
from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, SmallInteger, String, Text, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from codewright_api.settings import get_settings


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB}


class Project(Base):
    """A codebase Codewright works on (connected or created). Later phases add source and workspace details."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    # draft | importing | ready | failed
    status: Mapped[str] = mapped_column(String(40), default="draft")
    source: Mapped[dict[str, Any]] = mapped_column(default=dict)  # {"kind": "zip" | "github" | ..., "ref": ...}
    instructions: Mapped[str] = mapped_column(Text, default="")  # project instructions, added to every prompt
    summary: Mapped[dict[str, Any]] = mapped_column(default=dict)  # files, size, languages, top-level entries
    secrets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)  # secret-scan findings
    error: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Run(Base):
    """One execution of a playbook. Its LangGraph thread id is the run id."""

    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    # None for requests without a project (e.g. general questions).
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"), index=True)
    playbook: Mapped[str] = mapped_column(String(40))  # README Section 5
    tier: Mapped[int] = mapped_column(SmallInteger)  # risk tier 0-3, README Section 3.2
    # created | running | waiting | completed | failed | cancelled
    status: Mapped[str] = mapped_column(String(20), default="created", index=True)
    llm_profile: Mapped[str] = mapped_column(String(20))
    inputs: Mapped[dict[str, Any]] = mapped_column(default=dict)  # validated by the playbook
    current_step: Mapped[str | None] = mapped_column(String(40))
    # The open interrupt (gate card or "model server unavailable" prompt), if the run is waiting.
    pending: Mapped[dict[str, Any] | None] = mapped_column()
    error: Mapped[str | None] = mapped_column(Text)
    # The chat that started the run, if any: its run card and Done card live there.
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Conversation(Base):
    """A chat (CODEWRIGHT.md Section 2.2). Messages form a tree; `head_id` is the leaf of the branch shown."""

    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="SET NULL"))
    title: Mapped[str] = mapped_column(String(200))
    pinned: Mapped[bool] = mapped_column(Boolean, default=False)
    head_id: Mapped[uuid.UUID | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class Message(Base):
    """One chat message. Editing a message or regenerating a reply adds a sibling (same parent): a new branch."""

    __tablename__ = "messages"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("messages.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(10))  # user | assistant
    kind: Mapped[str] = mapped_column(String(20), default="text")  # text | questions | confirm | run | done | ...
    content: Mapped[str] = mapped_column(Text, default="")
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    status: Mapped[str] = mapped_column(String(20), default="complete")  # complete | streaming | stopped | error
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Upload(Base):
    """A file attached in the chat (or to a project): stored on disk, secret-scanned, read as data only."""

    __tablename__ = "uploads"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    conversation_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("conversations.id", ondelete="CASCADE"))
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(100))
    size: Mapped[int] = mapped_column(BigInteger)
    kind: Mapped[str] = mapped_column(String(20))  # text | image | archive | other
    path: Mapped[str] = mapped_column(Text)
    secrets: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class MemoryItem(Base):
    """Project memory or user preferences (project_id None), e.g. answers from the missing-info check."""

    __tablename__ = "memory_items"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    project_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("projects.id", ondelete="CASCADE"))
    key: Mapped[str] = mapped_column(String(200))
    value: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(40), default="chat")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


class RunEvent(Base):
    """Timeline of a run; also replayed to SSE clients that (re)connect."""

    __tablename__ = "run_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(40))
    step: Mapped[str | None] = mapped_column(String(40))
    data: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Approval(Base):
    """Every gate decision (README: Approve / Edit / Reject with a reason)."""

    __tablename__ = "approvals"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    gate: Mapped[str] = mapped_column(String(20))
    subject: Mapped[str | None] = mapped_column(String(100))
    decision: Mapped[str] = mapped_column(String(10))
    comment: Mapped[str] = mapped_column(Text, default="")
    edits: Mapped[dict[str, Any]] = mapped_column(default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class Trace(Base):
    """Built-in trace store: every LLM call (and, later, tool call) with tokens and latency (README 7.2)."""

    __tablename__ = "traces"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    step: Mapped[str | None] = mapped_column(String(40))
    role: Mapped[str | None] = mapped_column(String(40))
    kind: Mapped[str] = mapped_column(String(10))  # "llm" | "tool"
    name: Mapped[str] = mapped_column(String(100))
    profile: Mapped[str | None] = mapped_column(String(20))
    model: Mapped[str | None] = mapped_column(String(200))
    input: Mapped[Any] = mapped_column(JSONB)
    output: Mapped[str | None] = mapped_column(Text)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0)
    latency_ms: Mapped[int] = mapped_column(Integer, default=0)
    status: Mapped[str] = mapped_column(String(10))
    error: Mapped[str | None] = mapped_column(Text)
    meta: Mapped[dict[str, Any]] = mapped_column("metadata", default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now(), index=True)


class AppSetting(Base):
    """Key/value settings changed in the dashboard (e.g. the active LLM profile and URL overrides)."""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def to_sqlalchemy_url(url: str) -> str:
    """Use the psycopg 3 driver for plain `postgresql://` URLs."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


@lru_cache
def get_engine() -> AsyncEngine:
    url = to_sqlalchemy_url(get_settings().database_url.get_secret_value())
    return create_async_engine(url, pool_pre_ping=True)


@lru_cache
def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(get_engine(), expire_on_commit=False)


async def get_session() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


SessionDep = Annotated[AsyncSession, Depends(get_session)]
