"""Realtime event types, publisher, and channel naming (Redis Pub/Sub).

Cung cấp:
- Helper functions tạo tên kênh theo tenant (restaurant_id).
- Event type constants cho mọi sự kiện realtime.
- ``RealtimePublisher`` — fire-and-forget publish, không raise lỗi để
  không block DB writes (design principle).
"""

from __future__ import annotations

import json
import logging
import time
from uuid import UUID

import redis.asyncio as aioredis

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Channel naming helpers
# ---------------------------------------------------------------------------


def kitchen_channel(restaurant_id: UUID) -> str:
    """Return the Redis Pub/Sub channel for kitchen updates of a restaurant.

    Format: ``rt:{restaurant_id}:kitchen``
    """
    return f"rt:{restaurant_id}:kitchen"


def session_channel(restaurant_id: UUID, session_id: UUID) -> str:
    """Return the Redis Pub/Sub channel for a specific customer session.

    Format: ``rt:{restaurant_id}:session:{session_id}``
    """
    return f"rt:{restaurant_id}:session:{session_id}"


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------


class EventTypes:
    """Named constants for all realtime event types used in QOrder."""

    ORDER_CREATED: str = "order.created"
    """New order placed (R3.3)."""

    ITEM_UPDATED: str = "item.updated"
    """Item status changed (R4.3)."""

    ITEM_CANCELLED: str = "item.cancelled"
    """Item cancelled (R11.6)."""

    STAFF_CALL_NEW: str = "staff_call.new"
    """Customer calls staff (R7.2)."""

    STAFF_CALL_ACK: str = "staff_call.ack"
    """Staff acknowledged call (R7.3)."""

    SESSION_CLOSED: str = "session.closed"
    """Session checkout complete (R6.2)."""

    SESSION_ABANDONED: str = "session.abandoned"
    """Session auto-abandoned (R13.4)."""

    SESSION_RESTORED: str = "session.restored"
    """Abandoned session restored to open (R13.5)."""


# ---------------------------------------------------------------------------
# Publisher
# ---------------------------------------------------------------------------


class RealtimePublisher:
    """Fire-and-forget publisher for Redis Pub/Sub realtime events.

    Design constraint: publish errors are logged but **never** raised so that
    database writes are not blocked by transient Redis issues.
    """

    @staticmethod
    async def publish(
        channel: str,
        event_type: str,
        payload: dict,
        redis_client: aioredis.Redis,
    ) -> None:
        """Serialize and publish an event to a Redis Pub/Sub channel.

        Parameters
        ----------
        channel:
            Target channel name (use ``kitchen_channel`` / ``session_channel``).
        event_type:
            One of ``EventTypes.*`` constants.
        payload:
            Arbitrary JSON-serializable dict merged into the message.
        redis_client:
            An active ``redis.asyncio.Redis`` instance.

        The published JSON message has the shape::

            {"type": "<event_type>", "seq": <nanosecond_timestamp>, ...payload}

        The ``seq`` field is a monotonically increasing nanosecond timestamp
        generated server-side. Clients use it for anti-stale protection during
        resync: events with ``seq`` lower than the client's last known state
        should be discarded (R4.8).
        """
        seq = time.time_ns()
        message = json.dumps(
            {"type": event_type, "seq": seq, **payload}, default=str
        )
        try:
            await redis_client.publish(channel, message)
        except Exception:
            logger.exception(
                "Failed to publish event %s to channel %s",
                event_type,
                channel,
            )
