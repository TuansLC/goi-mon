"""Pydantic response schemas for the public customer-facing endpoints (R2.2, R2.3, R3.1, R3.2, R3.3).

These schemas are used by the QR-resolve endpoint to return restaurant info,
table info, and the full menu grouped by category. Also includes order creation
request/response schemas.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from qorder_api.models.enums import OrderItemStatus


# ─── Menu Item (customer view) ───────────────────────────────────────────────


class CustomerMenuItemResponse(BaseModel):
    """A single menu item as seen by the customer."""

    id: UUID
    name: str
    description: str | None
    price: Decimal
    prep_time_minutes: int
    is_available: bool
    image_url: str | None
    image_large_url: str | None
    is_featured: bool
    category_id: UUID | None

    model_config = {"from_attributes": True}


# ─── Menu Category (customer view) ──────────────────────────────────────────


class CustomerMenuCategoryResponse(BaseModel):
    """A menu category with its nested items for the customer."""

    id: UUID
    name: str
    sort_order: int
    items: list[CustomerMenuItemResponse]


# ─── Restaurant & Table info ─────────────────────────────────────────────────


class QRRestaurantInfo(BaseModel):
    """Minimal restaurant info returned in the QR resolve response."""

    name: str
    slug: str
    currency: str
    logo_url: str | None


class QRTableInfo(BaseModel):
    """Minimal table info returned in the QR resolve response."""

    id: UUID
    table_number: str


# ─── Top-level QR resolve response ──────────────────────────────────────────


class QRResolveResponse(BaseModel):
    """Full response for ``GET /t/{qr_token}`` — everything the customer app needs."""

    restaurant: QRRestaurantInfo
    table: QRTableInfo
    menu: list[CustomerMenuCategoryResponse]


# ─── Order creation (R3.3, R3.4, R3.5, R3.6) ────────────────────────────────


class CreateOrderItemRequest(BaseModel):
    """A single item in the customer's cart."""

    menu_item_id: UUID
    quantity: int = Field(..., gt=0)
    note: str | None = None


class CreateOrderRequest(BaseModel):
    """Customer order submission — must contain at least one item (R3.6)."""

    items: list[CreateOrderItemRequest] = Field(..., min_length=1)


class OrderItemResponse(BaseModel):
    """A single order item in the creation response."""

    id: UUID
    menu_item_id: UUID
    name_snapshot: str
    price_snapshot: Decimal
    prep_time_snapshot: int
    quantity: int
    note: str | None
    status: OrderItemStatus
    requested_at: datetime

    model_config = {"from_attributes": True}


class CreateOrderResponse(BaseModel):
    """Response after successfully creating an order (R3.3)."""

    id: UUID
    table_session_id: UUID
    created_at: datetime
    items: list[OrderItemResponse]

    model_config = {"from_attributes": True}
