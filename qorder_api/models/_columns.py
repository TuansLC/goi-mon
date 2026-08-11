"""Reusable column factories for common patterns.

Keeps model definitions terse and consistent: UUID primary keys default to
``gen_random_uuid()`` (Postgres ``pgcrypto``) and timestamp columns default to
``now()`` at the database layer, matching the schema convention in design.md.
"""

from __future__ import annotations

import uuid

from sqlalchemy import TIMESTAMP, func, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import mapped_column


def uuid_pk():
    """UUID primary key with a server-side ``gen_random_uuid()`` default."""

    return mapped_column(
        PgUUID(as_uuid=True),
        primary_key=True,
        server_default=text("gen_random_uuid()"),
    )


def uuid_fk(target: str, *, nullable: bool = False, ondelete: str | None = None):
    """UUID foreign-key column pointing at ``target`` (``table.column``)."""

    from sqlalchemy import ForeignKey

    return mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey(target, ondelete=ondelete),
        nullable=nullable,
    )


def created_at_column():
    """``TIMESTAMPTZ NOT NULL DEFAULT now()`` creation timestamp."""

    return mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
    )


def updated_at_column():
    """``TIMESTAMPTZ NOT NULL DEFAULT now()`` that also bumps on UPDATE."""

    return mapped_column(
        TIMESTAMP(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )


def ts_column(*, nullable: bool = True, default_now: bool = False):
    """Generic ``TIMESTAMPTZ`` column (nullable by default, no server default)."""

    return mapped_column(
        TIMESTAMP(timezone=True),
        nullable=nullable,
        server_default=func.now() if default_now else None,
    )


__all__ = [
    "uuid",
    "uuid_pk",
    "uuid_fk",
    "created_at_column",
    "updated_at_column",
    "ts_column",
]
