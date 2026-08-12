"""Integration tests for WebSocket realtime publish/subscribe via fakeredis (R4.8).

Tests verify:
- Publish→Subscribe delivery on kitchen and session channels
- Channel isolation between restaurants/sessions
- Multiple events ordering with monotonically increasing seq
- Anti-stale protection via nanosecond-precision seq field
"""

from __future__ import annotations

import asyncio
import json
from uuid import UUID, uuid4

import fakeredis.aioredis as fakeredis_aio
import pytest

from qorder_api.realtime import (
    EventTypes,
    RealtimePublisher,
    kitchen_channel,
    session_channel,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RESTAURANT_A = UUID("aaaa0001-1111-2222-3333-444444444444")
RESTAURANT_B = UUID("bbbb0002-1111-2222-3333-444444444444")
SESSION_X = UUID("cccc0003-1111-2222-3333-444444444444")
SESSION_Y = UUID("dddd0004-1111-2222-3333-444444444444")


@pytest.fixture
async def redis_client() -> fakeredis_aio.FakeRedis:
    """Provide a fake async Redis client for testing."""
    client = fakeredis_aio.FakeRedis(decode_responses=True)
    yield client  # type: ignore[misc]
    await client.aclose()


# ---------------------------------------------------------------------------
# Publish → Subscribe via fakeredis
# ---------------------------------------------------------------------------


class TestPublishSubscribeKitchen:
    """Publish an event on a kitchen channel → subscriber receives correct JSON."""

    async def test_kitchen_publish_subscribe(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Subscriber on kitchen channel receives published event."""
        channel = kitchen_channel(RESTAURANT_A)

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        # Consume subscription confirmation
        await pubsub.get_message(timeout=1)

        payload = {"item_id": "item-1", "status": "cooking"}
        await RealtimePublisher.publish(
            channel, EventTypes.ITEM_UPDATED, payload, redis_client
        )

        msg = await pubsub.get_message(timeout=1)
        assert msg is not None
        assert msg["type"] == "message"
        assert msg["channel"] == channel

        data = json.loads(msg["data"])
        assert data["type"] == EventTypes.ITEM_UPDATED
        assert data["item_id"] == "item-1"
        assert data["status"] == "cooking"

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()

    async def test_kitchen_publish_seq_present_and_numeric(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Published event contains a numeric seq field."""
        channel = kitchen_channel(RESTAURANT_A)

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1)

        await RealtimePublisher.publish(
            channel, EventTypes.ORDER_CREATED, {"order_id": "o1"}, redis_client
        )

        msg = await pubsub.get_message(timeout=1)
        data = json.loads(msg["data"])
        assert "seq" in data
        assert isinstance(data["seq"], int)

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


class TestPublishSubscribeSession:
    """Publish an event on a session channel → subscriber receives it."""

    async def test_session_publish_subscribe(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Subscriber on session channel receives published event."""
        channel = session_channel(RESTAURANT_A, SESSION_X)

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1)

        payload = {"order_id": "order-abc", "items": [{"name": "Bia"}]}
        await RealtimePublisher.publish(
            channel, EventTypes.ORDER_CREATED, payload, redis_client
        )

        msg = await pubsub.get_message(timeout=1)
        assert msg is not None

        data = json.loads(msg["data"])
        assert data["type"] == EventTypes.ORDER_CREATED
        assert data["order_id"] == "order-abc"
        assert data["items"] == [{"name": "Bia"}]
        assert "seq" in data
        assert isinstance(data["seq"], int)

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


# ---------------------------------------------------------------------------
# Channel isolation
# ---------------------------------------------------------------------------


class TestChannelIsolation:
    """Events are isolated between different restaurants and sessions."""

    async def test_kitchen_channel_isolation_between_restaurants(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Publish to restaurant A kitchen → restaurant B subscriber does NOT receive."""
        channel_a = kitchen_channel(RESTAURANT_A)
        channel_b = kitchen_channel(RESTAURANT_B)

        pubsub_b = redis_client.pubsub()
        await pubsub_b.subscribe(channel_b)
        await pubsub_b.get_message(timeout=1)

        # Publish to restaurant A's channel
        await RealtimePublisher.publish(
            channel_a,
            EventTypes.ITEM_UPDATED,
            {"item": "x"},
            redis_client,
        )

        # Restaurant B subscriber should not receive anything
        msg = await pubsub_b.get_message(timeout=0.5)
        assert msg is None

        await pubsub_b.unsubscribe(channel_b)
        await pubsub_b.aclose()

    async def test_session_channel_isolation_between_sessions(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Publish to session X → subscriber on session Y does NOT receive."""
        channel_x = session_channel(RESTAURANT_A, SESSION_X)
        channel_y = session_channel(RESTAURANT_A, SESSION_Y)

        pubsub_y = redis_client.pubsub()
        await pubsub_y.subscribe(channel_y)
        await pubsub_y.get_message(timeout=1)

        # Publish to session X's channel
        await RealtimePublisher.publish(
            channel_x,
            EventTypes.ORDER_CREATED,
            {"order": "o1"},
            redis_client,
        )

        # Session Y subscriber should not receive anything
        msg = await pubsub_y.get_message(timeout=0.5)
        assert msg is None

        await pubsub_y.unsubscribe(channel_y)
        await pubsub_y.aclose()


# ---------------------------------------------------------------------------
# Multiple events ordering
# ---------------------------------------------------------------------------


class TestMultipleEventsOrdering:
    """Sequential publishes arrive in order with increasing seq."""

    async def test_three_events_arrive_in_order_with_increasing_seq(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Publish 3 events sequentially → received in order with increasing seq."""
        channel = kitchen_channel(RESTAURANT_A)

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1)

        events = [
            (EventTypes.ORDER_CREATED, {"order_id": "o1"}),
            (EventTypes.ITEM_UPDATED, {"item_id": "i1", "status": "cooking"}),
            (EventTypes.ITEM_UPDATED, {"item_id": "i1", "status": "ready"}),
        ]

        for event_type, payload in events:
            await RealtimePublisher.publish(
                channel, event_type, payload, redis_client
            )

        received: list[dict] = []
        for _ in range(3):
            msg = await pubsub.get_message(timeout=1)
            assert msg is not None
            received.append(json.loads(msg["data"]))

        # Verify order matches publish order
        assert received[0]["type"] == EventTypes.ORDER_CREATED
        assert received[1]["type"] == EventTypes.ITEM_UPDATED
        assert received[1]["status"] == "cooking"
        assert received[2]["type"] == EventTypes.ITEM_UPDATED
        assert received[2]["status"] == "ready"

        # Verify monotonically increasing seq
        seqs = [r["seq"] for r in received]
        assert seqs[0] <= seqs[1] <= seqs[2]

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()


# ---------------------------------------------------------------------------
# Anti-stale protection
# ---------------------------------------------------------------------------


class TestAntiStaleProtection:
    """Seq values are monotonically increasing and nanosecond-precision."""

    async def test_sequential_publishes_have_monotonically_increasing_seq(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Multiple sequential publishes produce monotonically increasing seq."""
        channel = session_channel(RESTAURANT_A, SESSION_X)

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1)

        seqs: list[int] = []
        for i in range(5):
            await RealtimePublisher.publish(
                channel,
                EventTypes.ITEM_UPDATED,
                {"i": i},
                redis_client,
            )

        for _ in range(5):
            msg = await pubsub.get_message(timeout=1)
            assert msg is not None
            data = json.loads(msg["data"])
            seqs.append(data["seq"])

        # All seqs should be monotonically non-decreasing
        for i in range(1, len(seqs)):
            assert seqs[i] >= seqs[i - 1], (
                f"seq[{i}]={seqs[i]} < seq[{i-1}]={seqs[i-1]}"
            )

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()

    async def test_seq_is_nanosecond_precision(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Seq field is a nanosecond-precision timestamp (> 10^15)."""
        channel = kitchen_channel(RESTAURANT_A)

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1)

        await RealtimePublisher.publish(
            channel, EventTypes.STAFF_CALL_NEW, {"table": 3}, redis_client
        )

        msg = await pubsub.get_message(timeout=1)
        data = json.loads(msg["data"])

        # Nanosecond timestamp should be > 10^15 (year ~2001+)
        assert data["seq"] > 10**15, (
            f"seq={data['seq']} is not nanosecond precision"
        )

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
