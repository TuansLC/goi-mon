"""Authentication endpoints: staff PIN login, admin login, and WS ticket (R12.1–R12.3, R12.10, R4.3).

Staff authenticate with a restaurant slug + shared PIN → short-lived JWT.
Admins authenticate with email + password → JWT with ``role=admin``.
WS ticket endpoint issues one-shot tickets for WebSocket authentication.
"""

from __future__ import annotations

import redis.asyncio as aioredis
from pydantic import BaseModel
from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.auth.jwt import (
    TokenError,
    create_access_token,
    decode_access_token,
)
from qorder_api.auth.passwords import verify_password, verify_pin
from qorder_api.auth.ws_ticket import issue_ws_ticket
from qorder_api.db import get_session
from qorder_api.models.enums import UserRole
from qorder_api.models.restaurant import Restaurant
from qorder_api.models.user import User
from qorder_api.redis import get_redis

router = APIRouter(prefix="/auth", tags=["auth"])


# ---------- Request / Response schemas ----------


class StaffLoginRequest(BaseModel):
    """Body for ``POST /auth/staff/login``."""

    restaurant_slug: str
    pin: str


class AdminLoginRequest(BaseModel):
    """Body for ``POST /auth/admin/login``."""

    email: str
    password: str


class TokenResponse(BaseModel):
    """Successful login response."""

    access_token: str
    token_type: str = "bearer"


class WsTicketRequest(BaseModel):
    """Body for ``POST /auth/ws-ticket``."""

    restaurant_slug: str


class WsTicketResponse(BaseModel):
    """Response with a one-shot WS ticket."""

    ticket: str


# ---------- Endpoints ----------


@router.post("/staff/login", response_model=TokenResponse)
async def staff_login(
    body: StaffLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Authenticate a staff member with restaurant slug + PIN.

    - Restaurant not found or inactive → 404
    - PIN incorrect → 401
    """
    # Find the restaurant by slug
    result = await session.execute(
        select(Restaurant).where(Restaurant.slug == body.restaurant_slug)
    )
    restaurant = result.scalar_one_or_none()

    if restaurant is None or not restaurant.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Restaurant not found or not active",
        )

    # Find the staff user for this restaurant
    result = await session.execute(
        select(User).where(
            User.restaurant_id == restaurant.id,
            User.role == UserRole.STAFF,
            User.is_active == True,  # noqa: E712
        )
    )
    staff_user = result.scalar_one_or_none()

    if staff_user is None or staff_user.pin_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_pin(body.pin, staff_user.pin_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token(
        user_id=staff_user.id,
        role=staff_user.role.value,
        restaurant_id=restaurant.id,
    )

    return TokenResponse(access_token=token)


@router.post("/admin/login", response_model=TokenResponse)
async def admin_login(
    body: AdminLoginRequest,
    session: AsyncSession = Depends(get_session),
) -> TokenResponse:
    """Authenticate an admin with email + password.

    - Bad credentials → 401
    """
    # Find admin user by email
    result = await session.execute(
        select(User).where(
            User.email == body.email,
            User.role == UserRole.ADMIN,
            User.is_active == True,  # noqa: E712
        )
    )
    admin_user = result.scalar_one_or_none()

    if admin_user is None or admin_user.password_hash is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    if not verify_password(body.password, admin_user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
        )

    token = create_access_token(
        user_id=admin_user.id,
        role=admin_user.role.value,
        restaurant_id=admin_user.restaurant_id,
    )

    return TokenResponse(access_token=token)


# ---------- WS Ticket Endpoint (R12.10, R4.3) ----------


@router.post("/ws-ticket", response_model=WsTicketResponse)
async def create_ws_ticket(
    body: WsTicketRequest,
    session: AsyncSession = Depends(get_session),
    redis_client: aioredis.Redis = Depends(get_redis),
    authorization: str | None = Header(default=None),
) -> WsTicketResponse:
    """Issue a one-shot WebSocket ticket.

    Behavior depends on the restaurant's ``kitchen_screen_requires_pin`` setting:
    - **PIN required** (default): caller must provide a valid Staff JWT in the
      ``Authorization: Bearer <token>`` header. The ticket carries ``user_id``.
    - **PIN not required**: anonymous access allowed; only the restaurant slug
      is needed. The ticket carries ``user_id=null``.

    Errors:
    - 404: restaurant not found or inactive
    - 401: PIN required but JWT missing or invalid
    - 403: PIN required but JWT role is not ``staff``/``admin``
    """
    from qorder_api.auth.dependencies import get_kitchen_pin_required

    # 1. Find restaurant by slug
    result = await session.execute(
        select(Restaurant).where(Restaurant.slug == body.restaurant_slug)
    )
    restaurant = result.scalar_one_or_none()

    if restaurant is None or not restaurant.is_active:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Restaurant not found or not active",
        )

    # 2. Check kitchen_screen_requires_pin
    pin_required = await get_kitchen_pin_required(restaurant.id, session)

    user_id = None

    if pin_required:
        # 3. Require Staff JWT
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Staff JWT required when kitchen PIN is enabled",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = authorization.split(" ", 1)[1]
        try:
            payload = decode_access_token(token)
        except TokenError:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired token",
                headers={"WWW-Authenticate": "Bearer"},
            )

        # Must be staff or admin
        if payload.role not in ("staff", "admin"):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Staff or admin role required",
            )

        # Ensure the token belongs to this restaurant
        if payload.restaurant_id != restaurant.id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Token does not belong to this restaurant",
            )

        user_id = payload.sub
    # else: pin NOT required → anonymous, user_id stays None

    # 4. Issue ticket
    ticket = await issue_ws_ticket(
        restaurant_id=restaurant.id,
        role="staff",
        user_id=user_id,
        redis_client=redis_client,
    )

    return WsTicketResponse(ticket=ticket)
