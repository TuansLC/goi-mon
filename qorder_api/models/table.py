"""``tables`` — physical tables. QR codes map to a random ``qr_token`` (R2.1).

``table_number`` can repeat across tenants, so it is unique only within a
restaurant; ``qr_token`` is globally unique and never exposes the real id.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import Boolean, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from qorder_api.db import Base
from qorder_api.models._columns import created_at_column, uuid_fk, uuid_pk


class Table(Base):
    """A physical table within a restaurant."""

    __tablename__ = "tables"

    id: Mapped[uuid.UUID] = uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = uuid_fk(
        "restaurants.id", ondelete="CASCADE"
    )
    table_number: Mapped[str] = mapped_column(String, nullable=False)
    qr_token: Mapped[str] = mapped_column(String, nullable=False)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint("qr_token", name="uq_tables_qr_token"),
        UniqueConstraint(
            "restaurant_id", "table_number", name="uq_tables_restaurant_number"
        ),
    )
