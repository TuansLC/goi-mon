"""Pydantic schemas for menu categories and menu items (R8.1, R3.2, R5.3).

Request schemas validate incoming data; response schemas control serialization.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import BaseModel, Field


# ─── Menu Category ───────────────────────────────────────────────────────────


class MenuCategoryCreate(BaseModel):
    """Body for creating a menu category."""

    name: str = Field(..., min_length=1, max_length=200)
    sort_order: int = Field(default=0, ge=0)


class MenuCategoryUpdate(BaseModel):
    """Body for updating a menu category. All fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    sort_order: int | None = Field(default=None, ge=0)
    is_active: bool | None = None


class MenuCategoryResponse(BaseModel):
    """Response schema for a menu category."""

    id: UUID
    restaurant_id: UUID
    name: str
    sort_order: int
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}


# ─── Menu Item ───────────────────────────────────────────────────────────────


class MenuItemCreate(BaseModel):
    """Body for creating a menu item. ``prep_time_minutes`` is required."""

    name: str = Field(..., min_length=1, max_length=300)
    description: str | None = None
    price: Decimal = Field(..., ge=0)
    prep_time_minutes: int = Field(..., ge=0)
    category_id: UUID | None = None
    image_url: str | None = None
    sort_order: int = Field(default=0, ge=0)


class MenuItemUpdate(BaseModel):
    """Body for updating a menu item. All fields optional."""

    name: str | None = Field(default=None, min_length=1, max_length=300)
    description: str | None = None
    price: Decimal | None = Field(default=None, ge=0)
    prep_time_minutes: int | None = Field(default=None, ge=0)
    category_id: UUID | None = None
    is_available: bool | None = None
    is_active: bool | None = None
    image_url: str | None = None
    sort_order: int | None = Field(default=None, ge=0)


class MenuItemResponse(BaseModel):
    """Response schema for a menu item."""

    id: UUID
    restaurant_id: UUID
    category_id: UUID | None
    name: str
    description: str | None
    price: Decimal
    prep_time_minutes: int
    is_available: bool
    is_active: bool
    image_url: str | None
    sort_order: int
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


# ─── Presets ─────────────────────────────────────────────────────────────────


class PrepTimePresetsResponse(BaseModel):
    """Savory/light prep_time presets from restaurant_settings."""

    default_savory_minutes: int
    default_light_minutes: int
