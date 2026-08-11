"""``table_sessions`` — one "sitting" grouping many orders into one bill.

At most one ``open`` session may exist per table, enforced by a unique partial
index (R13.6). ``total_amount`` is only frozen when a session is ``closed``;
``open``/``abandoned`` sessions leave it NULL (R6.1, R13.4).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import Index, Numeric, text
from sqlalchemy.orm import Mapped, mapped_column

from qorder_api.db import Base
from qorder_api.models._columns import ts_column, uuid_fk, uuid_pk
from qorder_api.models.enums import SessionStatus, session_status_enum


class TableSession(Base):
    """A customer sitting at a table across multiple ordering rounds."""

    __tablename__ = "table_sessions"

    id: Mapped[uuid.UUID] = uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = uuid_fk(
        "restaurants.id", ondelete="CASCADE"
    )
    table_id: Mapped[uuid.UUID] = uuid_fk("tables.id", ondelete="CASCADE")
    status: Mapped[SessionStatus] = mapped_column(
        session_status_enum, nullable=False, server_default=SessionStatus.OPEN.value
    )
    opened_by: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", nullable=True, ondelete="SET NULL"
    )
    opened_at: Mapped[datetime] = ts_column(nullable=False, default_now=True)
    last_activity_at: Mapped[datetime] = ts_column(
        nullable=False, default_now=True
    )
    closed_at: Mapped[datetime | None] = ts_column(nullable=True)
    abandoned_at: Mapped[datetime | None] = ts_column(nullable=True)
    total_amount: Mapped[Decimal | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )

    __table_args__ = (
        # R13.6: at most one open session per table.
        Index(
            "uq_one_open_session_per_table",
            "table_id",
            unique=True,
            postgresql_where=text("status = 'open'"),
        ),
        Index("ix_table_sessions_table_status", "table_id", "status"),
        Index(
            "ix_table_sessions_status_activity",
            "status",
            "last_activity_at",
        ),
    )
