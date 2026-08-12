"""Pydantic response schemas for table sessions and session snapshots (R4.8, R13).

``SessionResponse`` is the standard response for session CRUD operations.
``SessionSnapshotResponse`` extends it with all order items for client resync.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel

from qorder_api.models.enums import CancelledBy, OrderItemStatus, SessionStatus


# ─── Order item within a snapshot ────────────────────────────────────────────


class OrderItemSnapshotResponse(BaseModel):
    """A single order item as part of a session snapshot (for client resync)."""

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
    served_at: datetime | None
    cancelled_at: datetime | None
    cancelled_by: CancelledBy | None
    cancel_reason: str | None

    model_config = {"from_attributes": True}


# ─── Session response ────────────────────────────────────────────────────────


class SessionResponse(BaseModel):
    """Standard response for a table session."""

    id: UUID
    restaurant_id: UUID
    table_id: UUID
    status: SessionStatus
    opened_by: UUID | None
    opened_at: datetime
    last_activity_at: datetime
    closed_at: datetime | None
    abandoned_at: datetime | None
    total_amount: Decimal | None

    model_config = {"from_attributes": True}


# ─── Session snapshot (resync) ───────────────────────────────────────────────


class SessionSnapshotResponse(BaseModel):
    """Session info + all order items for client resync (R4.8)."""

    id: UUID
    restaurant_id: UUID
    table_id: UUID
    status: SessionStatus
    opened_by: UUID | None
    opened_at: datetime
    last_activity_at: datetime
    closed_at: datetime | None
    abandoned_at: datetime | None
    total_amount: Decimal | None
    items: list[OrderItemSnapshotResponse]

    model_config = {"from_attributes": True}


# ─── Checkout response (R6.1, R6.2, R6.7) ───────────────────────────────────


class CancelledItemSummary(BaseModel):
    """Summary of an auto-cancelled item returned in checkout response (R6.7)."""

    id: UUID
    name_snapshot: str
    quantity: int
    status_before: str
    """Status before cancellation (pending/cooking/ready)."""

    model_config = {"from_attributes": True}


class CheckoutResponse(BaseModel):
    """Response for POST /sessions/{id}/checkout (R6.1, R6.2, R6.7).

    Includes session info, computed total_amount (served items only),
    and a list of items that were auto-cancelled at checkout.
    """

    session: SessionResponse
    total_amount: Decimal
    auto_cancelled_items: list[CancelledItemSummary]
    """Items auto-cancelled at checkout (R6.7 warning for FE)."""
    dismissed_calls_count: int
    """Number of pending staff calls dismissed (R6.9)."""


# ─── Restore response (R13.5, R13.7) ────────────────────────────────────────


class RestoreResponse(BaseModel):
    """Response for POST /sessions/{id}/restore (R13.5).

    ``action`` indicates which path was taken:
    - ``"restored"`` — session moved back to ``open`` (table had no open session).
    - ``"checked_out"`` — session moved directly to ``closed`` (table already
      had an open session, so direct checkout was performed).
    """

    session: SessionResponse
    action: str
    """Either 'restored' or 'checked_out'."""
    total_amount: Decimal | None = None
    """Only set when action='checked_out'."""
    auto_cancelled_items: list[CancelledItemSummary] = []
    """Only populated when action='checked_out'."""
    dismissed_calls_count: int = 0
    """Number of pending staff calls dismissed (only for 'checked_out')."""
