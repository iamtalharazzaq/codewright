"""Database engine, session dependency and ORM models."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import datetime
from functools import lru_cache
from typing import Annotated

from fastapi import Depends
from sqlalchemy import DateTime, Engine, String, create_engine, func
from sqlalchemy.orm import DeclarativeBase, Mapped, Session, mapped_column, sessionmaker

from monoshift_api.settings import get_settings


class Base(DeclarativeBase):
    pass


class Project(Base):
    """A monolith being audited or converted. Later phases add source, workspace and run links."""

    __tablename__ = "projects"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    mode: Mapped[str] = mapped_column(String(20))  # "conversion" | "audit"
    status: Mapped[str] = mapped_column(String(40), default="draft")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )


def to_sqlalchemy_url(url: str) -> str:
    """Use the psycopg 3 driver for plain `postgresql://` URLs."""
    if url.startswith("postgresql://"):
        return "postgresql+psycopg://" + url.removeprefix("postgresql://")
    return url


@lru_cache
def get_engine() -> Engine:
    url = to_sqlalchemy_url(get_settings().database_url.get_secret_value())
    return create_engine(url, pool_pre_ping=True)


def get_session() -> Iterator[Session]:
    with sessionmaker(get_engine(), expire_on_commit=False)() as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
