"""Pydantic schemas for kitchen endpoints (R4.1–R4.7, R11.4).

Includes the request body for status updates, cancel requests, and the response model
for order items returned from the kitchen router.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field

from qorder_api.models.enums import CancelledBy, OrderItemStatus


class SetItemStatusRequest(BaseModel):
    """Request body for ``POST /kitchen/items/{item_id}/status``."""

    to: OrderItemStatus = Field(
        ...,
        description="Trạng thái đích: cooking, ready, served, hoặc pending (undo).",
    )


class CancelItemRequest(BaseModel):
    """Request body for cancel endpoints (R11.2, R11.4). Reason is optional."""

    reason: str | None = Field(
        None,
        description="Lý do huỷ (tuỳ chọn).",
        max_length=500,
    )


class CancelledItemResponse(BaseModel):
    """Response model for an order item after cancellation."""

    id: UUID
    order_id: UUID
    menu_item_id: UUID
    name_snapshot: str
    price_snapshot: Decimal
    prep_time_snapshot: int
    quantity: int
    note: str | None
    status: OrderItemStatus
    requested_at: datetime
    cancelled_by: CancelledBy | None
    cancelled_at: datetime | None
    cancel_reason: str | None

    model_config = {"from_attributes": True}


class KitchenOrderItemResponse(BaseModel):
    """Response model for an order item after status update."""

    id: UUID
    order_id: UUID
    menu_item_id: UUID
    name_snapshot: str
    price_snapshot: Decimal
    prep_time_snapshot: int
    quantity: int
    note: str | None
    status: OrderItemStatus
    requested_at: datetime
    served_by: UUID | None
    served_at: datetime | None

    model_config = {"from_attributes": True}


class KitchenBoardItemResponse(BaseModel):
    """Response model for a single item on the kitchen board (R5, GET /kitchen/board).

    Includes all relevant item fields plus the dynamically computed ``overdue_level``.
    """

    id: UUID
    order_id: UUID
    menu_item_id: UUID
    name_snapshot: str
    price_snapshot: Decimal
    prep_time_snapshot: int
    quantity: int
    note: str | None
    status: OrderItemStatus
    requested_at: datetime
    overdue_level: int | None = Field(
        None,
        description=(
            "Dynamically computed overdue level: 0 (on time), 1 (slightly late), "
            "2 (moderately late), 3 (very late). None if prep_time_snapshot == 0."
        ),
    )

    model_config = {"from_attributes": True}


class KitchenBoardResponse(BaseModel):
    """Response wrapper for GET /kitchen/board."""

    items: list[KitchenBoardItemResponse]
