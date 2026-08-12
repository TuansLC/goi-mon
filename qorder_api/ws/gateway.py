"""WebSocket gateway endpoints and Redis Pub/Sub bridge (R4.3, R4.8, R7.2, R10.2).

Two WebSocket endpoints:
- ``WS /ws/kitchen?ticket={ticket}`` — staff kitchen board (authenticated via one-shot ticket).
- ``WS /ws/t/{qr_token}`` — customer session (anonymous, resolved via QR token).

Both endpoints subscribe to the appropriate Redis Pub/Sub channel and forward
messages to the connected WebSocket client in real time.

Resync Protocol (R4.8)
======================
When a client (re)connects after a network interruption, the following protocol
ensures no stale data overwrites a fresher snapshot:

1. **Client calls REST snapshot first:**
   - Kitchen: ``GET /kitchen/board`` (returns current board state).
   - Customer: ``GET /t/{qr_token}/session`` (returns session + all order items).

2. **Client opens WebSocket connection** after the snapshot response is received.

3. **Anti-stale filtering (client-side):**
   Every event published via ``RealtimePublisher`` contains a ``seq`` field
   (nanosecond timestamp). The client records the ``seq`` of the most recent
   event it processes (or uses the snapshot's ``last_activity_at`` as baseline).
   Events arriving with ``seq`` <= last processed ``seq`` are **discarded** by the
   client — they represent state already included in the snapshot.

4. **Server does NOT enforce ordering** — it only provides the ``seq``. Ordering
   logic lives entirely on the client side for simplicity.
"""

from __future__ import annotations

import asyncio
import logging

import redis.asyncio as aioredis
from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.auth.ws_ticket import verify_ws_ticket
from qorder_api.db import async_session_factory
from qorder_api.models.restaurant import Restaurant
from qorder_api.models.table import Table
from qorder_api.realtime import session_channel
from qorder_api.redis import _get_pool
from qorder_api.services.session_service import SessionService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ws", tags=["websocket"])

# Custom WebSocket close codes
WS_CLOSE_INVALID_TICKET = 4401
WS_CLOSE_INVALID_QR = 4404


# ---------------------------------------------------------------------------
# Redis → WebSocket bridge
# ---------------------------------------------------------------------------


async def _bridge_redis_to_ws(
    pubsub: aioredis.client.PubSub,
    websocket: WebSocket,
) -> None:
    """Read from Redis pubsub and forward messages to the WebSocket client.

    Runs as an asyncio task. Exits silently when the WebSocket is closed
    or the pubsub is unsubscribed.
    """
    try:
        async for message in pubsub.listen():
            if message["type"] == "message":
                await websocket.send_text(message["data"])
    except Exception:
        pass  # Connection closed or cancelled


# ---------------------------------------------------------------------------
# Helper: dedicated Redis client for pubsub
# ---------------------------------------------------------------------------


def _pubsub_redis() -> aioredis.Redis:
    """Create a dedicated Redis client for Pub/Sub (not request-scoped)."""
    return aioredis.Redis(connection_pool=_get_pool())


# ---------------------------------------------------------------------------
# WS /ws/kitchen — Staff kitchen board
# ---------------------------------------------------------------------------


@router.websocket("/kitchen")
async def ws_kitchen(websocket: WebSocket) -> None:
    """WebSocket for the kitchen board. Authenticates via one-shot ticket.

    Query params:
        ticket: one-shot WS ticket obtained from ``POST /auth/ws-ticket``.

    Close codes:
        4401 — invalid, expired, or already-used ticket.
    """
    ticket = websocket.query_params.get("ticket")
    if not ticket:
        await websocket.close(code=WS_CLOSE_INVALID_TICKET)
        return

    # Verify ticket using a dedicated Redis connection
    redis_client = _pubsub_redis()
    try:
        payload = await verify_ws_ticket(ticket, redis_client)
    finally:
        await redis_client.aclose()

    if payload is None:
        await websocket.close(code=WS_CLOSE_INVALID_TICKET)
        return

    restaurant_id = payload["restaurant_id"]
    channel_name = f"rt:{restaurant_id}:kitchen"

    await websocket.accept()

    # Subscribe to the kitchen channel with a dedicated pubsub connection
    pubsub_client = _pubsub_redis()
    pubsub = pubsub_client.pubsub()
    await pubsub.subscribe(channel_name)

    bridge_task = asyncio.create_task(_bridge_redis_to_ws(pubsub, websocket))

    try:
        # Keep connection alive — wait for client messages (ping/pong or close)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass
        await pubsub.unsubscribe(channel_name)
        await pubsub.aclose()
        await pubsub_client.aclose()


# ---------------------------------------------------------------------------
# WS /ws/t/{qr_token} — Customer session
# ---------------------------------------------------------------------------


@router.websocket("/t/{qr_token}")
async def ws_customer(websocket: WebSocket, qr_token: str) -> None:
    """WebSocket for a customer session. Resolved via QR token.

    Path params:
        qr_token: the table's unique QR token.

    Close codes:
        4404 — invalid or inactive QR token / restaurant.
    """
    # Resolve qr_token → table → restaurant using a short-lived DB session
    async with async_session_factory() as db_session:
        table, restaurant_id = await _resolve_qr_token(qr_token, db_session)

        if table is None:
            await websocket.close(code=WS_CLOSE_INVALID_QR)
            return

        # Get or open session for this table
        table_session = await SessionService.get_or_open(
            table_id=table.id,
            restaurant_id=restaurant_id,
            session=db_session,
        )
        session_id = table_session.id

    channel_name = session_channel(restaurant_id, session_id)

    await websocket.accept()

    # Subscribe to the session channel with a dedicated pubsub connection
    pubsub_client = _pubsub_redis()
    pubsub = pubsub_client.pubsub()
    await pubsub.subscribe(channel_name)

    bridge_task = asyncio.create_task(_bridge_redis_to_ws(pubsub, websocket))

    try:
        # Keep connection alive — wait for client messages (ping/pong or close)
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        bridge_task.cancel()
        try:
            await bridge_task
        except asyncio.CancelledError:
            pass
        await pubsub.unsubscribe(channel_name)
        await pubsub.aclose()
        await pubsub_client.aclose()


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _resolve_qr_token(
    qr_token: str,
    session: AsyncSession,
) -> tuple[Table | None, ...]:
    """Resolve a QR token to (table, restaurant_id) or (None, None).

    Returns (None, None) if the token is invalid, the table is inactive,
    or the restaurant is inactive.
    """
    # Look up the table by qr_token (must be active)
    table_result = await session.execute(
        select(Table).where(
            Table.qr_token == qr_token,
            Table.is_active.is_(True),
        )
    )
    table = table_result.scalar_one_or_none()

    if table is None:
        return None, None

    # Verify restaurant is active
    restaurant_result = await session.execute(
        select(Restaurant.id).where(
            Restaurant.id == table.restaurant_id,
            Restaurant.is_active.is_(True),
        )
    )
    restaurant_id = restaurant_result.scalar_one_or_none()

    if restaurant_id is None:
        return None, None

    return table, restaurant_id
