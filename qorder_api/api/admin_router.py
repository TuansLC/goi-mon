"""Admin-only endpoints: staff PIN reset and restaurant settings (R12.8, R12.9, R12.10).

All routes require ``role=admin`` enforced via ``require_role("admin")`` dependency.
The admin's ``restaurant_id`` is taken from the JWT — no need to pass it in the body.
"""

from __future__ import annotations

from pydantic import BaseModel, Field
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.auth.dependencies import CurrentUser, require_role
from qorder_api.auth.passwords import hash_pin
from qorder_api.db import get_session
from qorder_api.models.enums import UserRole
from qorder_api.models.restaurant import RestaurantSettings
from qorder_api.models.user import User

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_role("admin"))],
)


# ---------- Request / Response schemas ----------


class ResetPinRequest(BaseModel):
    """Body for ``POST /admin/staff/reset-pin``."""

    new_pin: str = Field(..., min_length=4, max_length=8)


class MessageResponse(BaseModel):
    """Generic success response."""

    message: str


class UpdateSettingsRequest(BaseModel):
    """Body for ``PATCH /admin/settings`` (R8.3, R1.3).

    All fields are optional — only provided fields will be updated.
    """

    kitchen_screen_requires_pin: bool | None = None
    currency: str | None = None
    logo_url: str | None = None
    timezone: str | None = None
    default_savory_minutes: int | None = Field(default=None, ge=0)
    default_light_minutes: int | None = Field(default=None, ge=0)
    session_timeout_hours: int | None = Field(default=None, ge=1)
    staff_call_cooldown_seconds: int | None = Field(default=None, ge=0)
    report_sheet_id: str | None = None
    report_sync_cron: str | None = None
    bill_footer_note: str | None = None


class SettingsResponse(BaseModel):
    """Response after updating settings — returns ALL configurable fields."""

    kitchen_screen_requires_pin: bool
    currency: str
    logo_url: str | None
    timezone: str
    default_savory_minutes: int
    default_light_minutes: int
    session_timeout_hours: int
    staff_call_cooldown_seconds: int
    report_sheet_id: str | None
    report_sync_cron: str
    bill_footer_note: str | None


# ---------- Endpoints ----------


@router.post("/staff/reset-pin", response_model=MessageResponse)
async def reset_staff_pin(
    body: ResetPinRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> MessageResponse:
    """Reset the staff PIN for the admin's restaurant (R12.8).

    Finds the staff user belonging to the same restaurant as the admin
    and updates their ``pin_hash`` with the new hashed PIN.
    """
    # Find the staff user for this restaurant
    result = await session.execute(
        select(User).where(
            User.restaurant_id == user.restaurant_id,
            User.role == UserRole.STAFF,
            User.is_active == True,  # noqa: E712
        )
    )
    staff_user = result.scalar_one_or_none()

    if staff_user is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="No active staff user found for this restaurant",
        )

    staff_user.pin_hash = hash_pin(body.new_pin)
    session.add(staff_user)
    await session.commit()

    return MessageResponse(message="PIN reset successfully")


@router.get("/settings", response_model=SettingsResponse)
async def get_settings(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    """Return the current restaurant settings (R8.3).

    Allows the admin to view all configurable fields before patching.
    """
    result = await session.execute(
        select(RestaurantSettings).where(
            RestaurantSettings.restaurant_id == user.restaurant_id,
        )
    )
    settings = result.scalar_one_or_none()

    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Restaurant settings not found",
        )

    return SettingsResponse(
        kitchen_screen_requires_pin=settings.kitchen_screen_requires_pin,
        currency=settings.currency,
        logo_url=settings.logo_url,
        timezone=settings.timezone,
        default_savory_minutes=settings.default_savory_minutes,
        default_light_minutes=settings.default_light_minutes,
        session_timeout_hours=settings.session_timeout_hours,
        staff_call_cooldown_seconds=settings.staff_call_cooldown_seconds,
        report_sheet_id=settings.report_sheet_id,
        report_sync_cron=settings.report_sync_cron,
        bill_footer_note=settings.bill_footer_note,
    )


@router.patch("/settings", response_model=SettingsResponse)
async def update_settings(
    body: UpdateSettingsRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> SettingsResponse:
    """Update restaurant settings (R8.3, R1.3, R12.9).

    Only fields present in the request body are updated.
    Supports: countdown presets, timeout, PIN flag, cooldown, currency,
    report_sheet_id, and more.
    """
    result = await session.execute(
        select(RestaurantSettings).where(
            RestaurantSettings.restaurant_id == user.restaurant_id,
        )
    )
    settings = result.scalar_one_or_none()

    if settings is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Restaurant settings not found",
        )

    # Apply only provided (non-default) fields
    update_data = body.model_dump(exclude_unset=True)
    for field_name, value in update_data.items():
        setattr(settings, field_name, value)

    session.add(settings)
    await session.commit()
    await session.refresh(settings)

    return SettingsResponse(
        kitchen_screen_requires_pin=settings.kitchen_screen_requires_pin,
        currency=settings.currency,
        logo_url=settings.logo_url,
        timezone=settings.timezone,
        default_savory_minutes=settings.default_savory_minutes,
        default_light_minutes=settings.default_light_minutes,
        session_timeout_hours=settings.session_timeout_hours,
        staff_call_cooldown_seconds=settings.staff_call_cooldown_seconds,
        report_sheet_id=settings.report_sheet_id,
        report_sync_cron=settings.report_sync_cron,
        bill_footer_note=settings.bill_footer_note,
    )
