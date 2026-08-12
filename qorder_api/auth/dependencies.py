"""FastAPI dependencies for authentication and role-based authorization (R12.5, R12.10).

Provides:
- ``get_current_user``: extracts and verifies JWT from Authorization header.
- ``require_role(*roles)``: factory returning a dependency that enforces role membership.
- ``CurrentUser``: type alias for injecting the verified :class:`TokenPayload`.
- ``get_kitchen_pin_required``: reads ``kitchen_screen_requires_pin`` from restaurant settings.
"""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.auth.jwt import TokenError, TokenPayload, decode_access_token

_bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer_scheme),
) -> TokenPayload:
    """Extract and verify JWT from the ``Authorization: Bearer <token>`` header.

    Raises:
        HTTPException 401: If the header is missing, malformed, or the token
            is invalid/expired.
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authentication credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = decode_access_token(credentials.credentials)
    except TokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return payload


# Convenience type alias for route signatures:
#   async def my_route(user: CurrentUser): ...
CurrentUser = Annotated[TokenPayload, Depends(get_current_user)]


def require_role(*roles: str):
    """Return a dependency that checks the authenticated user has one of the given roles.

    Usage::

        @router.post("/admin-only", dependencies=[Depends(require_role("admin"))])
        async def admin_only(): ...

        # Or allow multiple roles:
        @router.post("/staff-or-admin", dependencies=[Depends(require_role("staff", "admin"))])
        async def staff_or_admin(): ...

    Raises:
        HTTPException 403: If the user's role is not in the allowed set.
    """

    async def _role_checker(current_user: CurrentUser) -> TokenPayload:
        if current_user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{current_user.role}' is not authorized. Required: {', '.join(roles)}",
            )
        return current_user

    return _role_checker


# --- Kitchen screen guard helper (R12.10) ---


async def get_kitchen_pin_required(
    restaurant_id: UUID,
    session: AsyncSession,
) -> bool:
    """Return whether the kitchen screen requires PIN login for a restaurant.

    Reads ``restaurant_settings.kitchen_screen_requires_pin`` for the given
    restaurant. Defaults to ``True`` if no settings row exists (safe default).

    This helper is used by the kitchen WebSocket/HTTP guard to decide whether
    to enforce staff PIN authentication before granting access.
    """
    from qorder_api.models.restaurant import RestaurantSettings

    result = await session.execute(
        select(RestaurantSettings.kitchen_screen_requires_pin).where(
            RestaurantSettings.restaurant_id == restaurant_id,
        )
    )
    value = result.scalar_one_or_none()

    # Default to True (require PIN) if settings row doesn't exist
    return value if value is not None else True
