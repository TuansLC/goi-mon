"""SQLAlchemy ORM models (PostgreSQL).

Importing this package registers every model on ``Base.metadata`` so Alembic
autogenerate and ``metadata.create_all`` see the full schema. Enum types are
re-exported for use by services and the initial migration.
"""

from __future__ import annotations

from qorder_api.models.enums import (
    ALL_ENUMS,
    CancelledBy,
    OrderItemStatus,
    SessionStatus,
    StaffCallStatus,
    UserRole,
    cancelled_by_enum,
    order_item_status_enum,
    session_status_enum,
    staff_call_status_enum,
    user_role_enum,
)
from qorder_api.models.menu import MenuCategory, MenuItem
from qorder_api.models.order import Order, OrderItem
from qorder_api.models.restaurant import Restaurant, RestaurantSettings
from qorder_api.models.session import TableSession
from qorder_api.models.staff_call import StaffCall
from qorder_api.models.table import Table
from qorder_api.models.user import User

__all__ = [
    # Tables
    "Restaurant",
    "RestaurantSettings",
    "User",
    "Table",
    "MenuCategory",
    "MenuItem",
    "TableSession",
    "Order",
    "OrderItem",
    "StaffCall",
    # Enum Python types
    "OrderItemStatus",
    "SessionStatus",
    "UserRole",
    "CancelledBy",
    "StaffCallStatus",
    # SQLAlchemy enum type objects
    "order_item_status_enum",
    "session_status_enum",
    "user_role_enum",
    "cancelled_by_enum",
    "staff_call_status_enum",
    "ALL_ENUMS",
]
