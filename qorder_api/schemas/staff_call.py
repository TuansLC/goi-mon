"""Pydantic response schemas for staff call endpoints (R7).

Used by customer call endpoint and kitchen ack endpoint.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel

from qorder_api.models.enums import StaffCallStatus


class StaffCallResponse(BaseModel):
    """Response for a staff call record."""

    id: UUID
    restaurant_id: UUID
    table_id: UUID
    table_session_id: UUID
    status: StaffCallStatus
    created_at: datetime
    acknowledged_at: datetime | None = None
    acknowledged_by: UUID | None = None

    model_config = {"from_attributes": True}


class StaffCallCooldownResponse(BaseModel):
    """Response when customer is within cooldown (soft rejection)."""

    message: str
    cooldown: bool = True
