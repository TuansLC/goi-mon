"""Ordering models: ``orders`` (one round) and ``order_items`` (per dish).

``order_items`` is the heart of the kitchen state machine. It snapshots name,
price and prep time at order time so later menu edits never rewrite history
(design notes 3 & 4). Status transitions are done with compare-and-swap in the
service layer; the DB only guards value ranges via CHECK constraints.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    CheckConstraint,
    Index,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from qorder_api.db import Base
from qorder_api.models._columns import (
    created_at_column,
    ts_column,
    uuid_fk,
    uuid_pk,
)
from qorder_api.models.enums import (
    CancelledBy,
    OrderItemStatus,
    cancelled_by_enum,
    order_item_status_enum,
)


class Order(Base):
    """One "submit" of a cart; many orders belong to one session (R3.4)."""

    __tablename__ = "orders"

    id: Mapped[uuid.UUID] = uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = uuid_fk(
        "restaurants.id", ondelete="CASCADE"
    )
    table_session_id: Mapped[uuid.UUID] = uuid_fk(
        "table_sessions.id", ondelete="CASCADE"
    )
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = created_at_column()


class OrderItem(Base):
    """A single dish within an order round."""

    __tablename__ = "order_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = uuid_fk(
        "restaurants.id", ondelete="CASCADE"
    )
    order_id: Mapped[uuid.UUID] = uuid_fk("orders.id", ondelete="CASCADE")
    menu_item_id: Mapped[uuid.UUID] = uuid_fk(
        "menu_items.id", ondelete="RESTRICT"
    )
    name_snapshot: Mapped[str] = mapped_column(String, nullable=False)
    price_snapshot: Mapped[Decimal] = mapped_column(
        Numeric(12, 2), nullable=False
    )
    prep_time_snapshot: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    note: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[OrderItemStatus] = mapped_column(
        order_item_status_enum,
        nullable=False,
        server_default=OrderItemStatus.PENDING.value,
    )
    requested_at: Mapped[datetime] = ts_column(
        nullable=False, default_now=True
    )
    served_by: Mapped[uuid.UUID | None] = uuid_fk(
        "users.id", nullable=True, ondelete="SET NULL"
    )
    served_at: Mapped[datetime | None] = ts_column(nullable=True)
    cancelled_by: Mapped[CancelledBy | None] = mapped_column(
        cancelled_by_enum, nullable=True
    )
    cancelled_at: Mapped[datetime | None] = ts_column(nullable=True)
    cancel_reason: Mapped[str | None] = mapped_column(String, nullable=True)

    __table_args__ = (
        CheckConstraint(
            "prep_time_snapshot >= 0",
            name="ck_order_items_prep_time_nonneg",
        ),
        CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
        Index("ix_order_items_order", "order_id"),
        Index("ix_order_items_restaurant_status", "restaurant_id", "status"),
    )
