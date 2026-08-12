"""JWT creation and verification (R12.4).

Every token carries ``role``, ``restaurant_id``, and ``sub`` (user_id) claims
so downstream middleware can enforce tenant isolation without a DB lookup.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from uuid import UUID

from jose import JWTError, jwt
from pydantic import BaseModel

from qorder_api.config import get_settings


class TokenError(Exception):
    """Raised when a JWT cannot be decoded or has expired."""


class TokenPayload(BaseModel):
    """Parsed JWT claims returned by :func:`decode_access_token`."""

    sub: UUID
    restaurant_id: UUID
    role: str


def create_access_token(
    user_id: UUID,
    role: str,
    restaurant_id: UUID,
) -> str:
    """Create a signed JWT with standard QOrder claims.

    Claims included:
    - ``sub``: user id (str)
    - ``role``: ``"admin"`` | ``"staff"``
    - ``restaurant_id``: tenant scope (str)
    - ``exp``: expiration timestamp
    """
    settings = get_settings()
    expire = datetime.now(timezone.utc) + timedelta(
        minutes=settings.access_token_expire_minutes
    )
    payload = {
        "sub": str(user_id),
        "role": role,
        "restaurant_id": str(restaurant_id),
        "exp": expire,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> TokenPayload:
    """Decode and verify a JWT, returning a typed :class:`TokenPayload`.

    Raises:
        TokenError: If the token is invalid, expired, or tampered with.
    """
    raw = _decode_raw(token)
    try:
        return TokenPayload(
            sub=UUID(raw["sub"]),
            restaurant_id=UUID(raw["restaurant_id"]),
            role=raw["role"],
        )
    except (KeyError, ValueError) as exc:
        raise TokenError(f"Malformed token payload: {exc}") from exc


def decode_token(token: str) -> dict:
    """Decode and verify a JWT, returning the raw payload dict.

    Kept for backward compatibility — prefer :func:`decode_access_token`
    for typed access.

    Raises:
        TokenError: If the token is invalid, expired, or tampered with.
    """
    return _decode_raw(token)


def _decode_raw(token: str) -> dict:
    """Internal: decode JWT to raw dict."""
    settings = get_settings()
    try:
        payload: dict = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=[settings.jwt_algorithm],
        )
    except JWTError as exc:
        raise TokenError(f"Invalid token: {exc}") from exc
    return payload
