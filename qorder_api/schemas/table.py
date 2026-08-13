"""Pydantic schemas for table CRUD (R2.1, R2.5, R2.6, R8.2).

Request schemas validate incoming data; response schemas control serialization.
"""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field


class TableCreate(BaseModel):
    """Body for creating a table. ``table_number`` is required."""

    table_number: str = Field(..., min_length=1, max_length=50)


class TableUpdate(BaseModel):
    """Body for updating a table. All fields optional."""

    table_number: str | None = Field(default=None, min_length=1, max_length=50)
    is_active: bool | None = None


class TableResponse(BaseModel):
    """Response schema for a table."""

    id: UUID
    restaurant_id: UUID
    table_number: str
    qr_token: str
    qr_image_url: str | None = None
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
