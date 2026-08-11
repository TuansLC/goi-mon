"""``users`` — staff + admin accounts merged in one table (R12.7).

Credential columns are nullable because staff authenticate with a shared PIN
hash while admins use email + password. A CHECK constraint (see
``__table_args__``) guarantees the right combination per role.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from qorder_api.db import Base
from qorder_api.models._columns import created_at_column, uuid_fk, uuid_pk
from qorder_api.models.enums import UserRole, user_role_enum


class User(Base):
    """A restaurant staff member or admin."""

    __tablename__ = "users"

    id: Mapped[uuid.UUID] = uuid_pk()
    restaurant_id: Mapped[uuid.UUID] = uuid_fk(
        "restaurants.id", ondelete="CASCADE"
    )
    role: Mapped[UserRole] = mapped_column(user_role_enum, nullable=False)
    email: Mapped[str | None] = mapped_column(String, nullable=True)
    password_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    pin_hash: Mapped[str | None] = mapped_column(String, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String, nullable=True)
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, server_default="true"
    )
    created_at: Mapped[datetime] = created_at_column()

    __table_args__ = (
        UniqueConstraint(
            "restaurant_id", "email", name="uq_users_restaurant_email"
        ),
        CheckConstraint(
            "(role = 'admin' AND email IS NOT NULL AND password_hash IS NOT NULL)"
            " OR (role = 'staff' AND pin_hash IS NOT NULL)",
            name="ck_users_role_credentials",
        ),
    )
