"""Tenant models: ``restaurants`` and its 1-1 ``restaurant_settings``.

Every business table carries ``restaurant_id`` for multi-tenant isolation
(R1.1). Configuration lives in a separate 1-1 table so it can grow without
churning the core ``restaurants`` row.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column, relationship

from qorder_api.db import Base
from qorder_api.models._columns import (
    created_at_column,
    updated_at_column,
    uuid_pk,
)


class Restaurant(Base):
    """A tenant (one restaurant/bar)."""

    __tablename__ = "restaurants"

    id: Mapped[uuid.UUID] = uuid_pk()
    slug: Mapped[str] = mapped_column(String, nullable=False)
    name: Mapped[str] = mapped_column(String, nullable=False)
    phone: Mapped[str | None] = mapped_column(String, nullable=True)
    address: Mapped[str | None] = mapped_column(Text, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    settings: Mapped["RestaurantSettings | None"] = relationship(
        back_populates="restaurant",
        uselist=False,
        lazy="selectin",
    )

    __table_args__ = (
        UniqueConstraint("slug", name="uq_restaurants_slug"),
    )


class RestaurantSettings(Base):
    """Per-tenant configuration (1-1 with :class:`Restaurant`)."""

    __tablename__ = "restaurant_settings"

    # 1-1: the tenant id is also the primary key.
    restaurant_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("restaurants.id", ondelete="CASCADE"),
        primary_key=True,
    )

    currency: Mapped[str] = mapped_column(
        String, nullable=False, server_default="VND"
    )
    logo_url: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(
        String, nullable=False, server_default="Asia/Ho_Chi_Minh"
    )
    default_savory_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="10"
    )
    default_light_minutes: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="5"
    )
    session_timeout_hours: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="6"
    )
    kitchen_screen_requires_pin: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    staff_call_cooldown_seconds: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="60"
    )
    report_sheet_id: Mapped[str | None] = mapped_column(String, nullable=True)
    report_sync_cron: Mapped[str] = mapped_column(
        String, nullable=False, server_default="0 * * * *"
    )
    bill_footer_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_at: Mapped[datetime] = updated_at_column()

    restaurant: Mapped["Restaurant"] = relationship(back_populates="settings")
