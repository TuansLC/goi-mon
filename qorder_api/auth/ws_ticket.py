"""WebSocket ticket issuance and verification (R12.10, R4.3).

Implements a one-shot, short-lived ticket mechanism for WebSocket authentication.
Browser WS handshakes cannot carry custom headers, so the flow is:

1. Client calls ``POST /auth/ws-ticket`` → server issues a ticket stored in Redis.
2. Client opens WS with ``?ticket=<ticket>`` query param.
3. Gateway verifies ticket via atomic ``GETDEL`` (one-shot) → allows or denies.
"""

from __future__ import annotations

import json
import secrets
from uuid import UUID

import redis.asyncio as aioredis

from qorder_api.config import get_settings


async def issue_ws_ticket(
    restaurant_id: UUID,
    role: str,
    user_id: UUID | None,
    redis_client: aioredis.Redis,
) -> str:
    """Generate a one-shot WS ticket and store it in Redis.

    The ticket key ``ws_ticket:{ticket}`` holds a JSON payload with the
    restaurant context and expires after ``ws_ticket_ttl_seconds`` (default 30s).

    Returns:
        The raw ticket string the client passes as a query param.
    """
    settings = get_settings()
    ticket = secrets.token_urlsafe(32)

    payload = json.dumps(
        {
            "restaurant_id": str(restaurant_id),
            "role": role,
            "user_id": str(user_id) if user_id else None,
        }
    )

    key = f"ws_ticket:{ticket}"
    await redis_client.set(key, payload, ex=settings.ws_ticket_ttl_seconds)

    return ticket


async def verify_ws_ticket(
    ticket: str,
    redis_client: aioredis.Redis,
) -> dict | None:
    """Consume a WS ticket atomically via GETDEL.

    Returns:
        Parsed dict ``{restaurant_id, role, user_id}`` if valid, or ``None``
        if the ticket does not exist (expired or already used).
    """
    key = f"ws_ticket:{ticket}"
    raw: bytes | None = await redis_client.getdel(key)

    if raw is None:
        return None

    return json.loads(raw)
