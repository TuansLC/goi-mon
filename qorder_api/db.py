"""Async database layer: engine, session factory, base model, session dependency.

PostgreSQL is the source of truth (R10.1). We use SQLAlchemy 2.0 async with
asyncpg. ``get_session`` is a FastAPI dependency that yields an ``AsyncSession``
and guarantees it is closed after the request.
"""

from __future__ import annotations

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from qorder_api.config import get_settings


class Base(DeclarativeBase):
    """Declarative base class for all ORM models."""


_settings = get_settings()

# ``pool_pre_ping`` avoids stale connections after DB idle timeouts on managed
# platforms (Supabase/Railway). ``future`` semantics are default in SA 2.0.
engine = create_async_engine(
    _settings.database_url,
    echo=_settings.debug,
    pool_pre_ping=True,
)

# ``expire_on_commit=False`` keeps ORM objects usable after commit, which is
# convenient when returning models straight from a request handler.
async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency yielding an ``AsyncSession`` scoped to a request."""

    async with async_session_factory() as session:
        yield session
