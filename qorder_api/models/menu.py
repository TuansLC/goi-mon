"""Menu models: ``menu_categories`` and ``menu_items``.

``prep_time_minutes`` is mandatory (admins must not forget it); ``0`` means the
item is served immediately with no countdown (e.g. drinks — R5.2). Items are
soft-hidden via ``is_active`` / marked out of stock via ``is_available`` so old
``order_items`` references stay intact (R8.1, R3.2).
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Integer,
    Numeric,
    String,
    Text,
)
from sqlalchemy.orm import Mapped, mapped_column

from qorder_api.db import Base
from qorder_api.models._columns import (
    created_at_column,
    updated_at_column,
    uuid_fk,
    uuid_pk,
)


class MenuCategory(Base):
    """A display group of menu items (R8.1)."""

    __tablename__ = "menu_categories"

    id: Mapped[uuid.UUID] = uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = uuid_fk(
        "restaurants.id", ondelete="CASCADE"
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = created_at_column()


class MenuItem(Base):
    """A single sellable menu item."""

    __tablename__ = "menu_items"

    id: Mapped[uuid.UUID] = uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = uuid_fk(
        "restaurants.id", ondelete="CASCADE"
    )
    category_id: Mapped[uuid.UUID | None] = uuid_fk(
        "menu_categories.id", nullable=True, ondelete="SET NULL"
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    price: Mapped[Decimal] = mapped_column(Numeric(12, 2), nullable=False)
    prep_time_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    # Thumbnail (400x400 WebP) shown in the menu list.
    image_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Larger variant (max side 1000px) used by the customer lightbox.
    image_large_url: Mapped[str | None] = mapped_column(String, nullable=True)
    # Highlighted in the "Món đặc trưng" carousel on the customer screen.
    is_featured: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="false"
    )
    sort_order: Mapped[int] = mapped_column(
        Integer, nullable=False, server_default="0"
    )
    created_at: Mapped[datetime] = created_at_column()
    updated_at: Mapped[datetime] = updated_at_column()

    __table_args__ = (
        CheckConstraint(
            "prep_time_minutes >= 0", name="ck_menu_items_prep_time_nonneg"
        ),
    )
