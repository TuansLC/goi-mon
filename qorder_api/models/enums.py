"""PostgreSQL native enum types shared across ORM models.

Each :class:`enum.Enum` is paired with a SQLAlchemy :class:`~sqlalchemy.Enum`
bound to a stable ``name`` so PostgreSQL creates a real ``CREATE TYPE`` enum.
``create_type=False`` hands lifecycle management to Alembic: the initial
migration creates and drops the types explicitly, avoiding duplicate
``CREATE TYPE`` statements when a type is reused across several columns.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum as SAEnum


class OrderItemStatus(str, enum.Enum):
    """Lifecycle of a single ordered item (R4.1, R11.1)."""

    PENDING = "pending"
    COOKING = "cooking"
    READY = "ready"
    SERVED = "served"
    CANCELLED = "cancelled"


class SessionStatus(str, enum.Enum):
    """Lifecycle of a table session (R13.1)."""

    OPEN = "open"
    CLOSED = "closed"
    ABANDONED = "abandoned"


class UserRole(str, enum.Enum):
    """Account role; ready to split into kitchen/waiter later (R12.7)."""

    STAFF = "staff"
    ADMIN = "admin"


class CancelledBy(str, enum.Enum):
    """Actor that cancelled an order item (R11.7)."""

    CUSTOMER = "customer"
    STAFF = "staff"
    SYSTEM = "system"


class StaffCallStatus(str, enum.Enum):
    """Lifecycle of a staff-call request (R7)."""

    PENDING = "pending"
    ACKNOWLEDGED = "acknowledged"


def _pg_enum(py_enum: type[enum.Enum], name: str) -> SAEnum:
    """Build a native PostgreSQL enum whose stored values are the ``.value``s.

    ``create_type=False`` so Alembic owns the ``CREATE TYPE`` / ``DROP TYPE``.
    """

    return SAEnum(
        py_enum,
        name=name,
        create_type=False,
        native_enum=True,
        values_callable=lambda e: [member.value for member in e],
    )


order_item_status_enum = _pg_enum(OrderItemStatus, "order_item_status")
session_status_enum = _pg_enum(SessionStatus, "session_status")
user_role_enum = _pg_enum(UserRole, "user_role")
cancelled_by_enum = _pg_enum(CancelledBy, "cancelled_by")
staff_call_status_enum = _pg_enum(StaffCallStatus, "staff_call_status")

# Ordered list used by the initial migration to create/drop the enum types.
ALL_ENUMS: tuple[SAEnum, ...] = (
    order_item_status_enum,
    session_status_enum,
    user_role_enum,
    cancelled_by_enum,
    staff_call_status_enum,
)
