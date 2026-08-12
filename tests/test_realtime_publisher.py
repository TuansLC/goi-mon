"""Tests for qorder_api.realtime — channel naming, event publishing, error handling."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, patch
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
# Channel naming
# ---------------------------------------------------------------------------

RID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
SID = UUID("11111111-2222-3333-4444-555555555555")


class TestChannelNaming:
    """Channel helpers produce correct Pub/Sub channel strings."""

    def test_kitchen_channel_format(self) -> None:
        result = kitchen_channel(RID)
        assert result == f"rt:{RID}:kitchen"

    def test_session_channel_format(self) -> None:
        result = session_channel(RID, SID)
        assert result == f"rt:{RID}:session:{SID}"

    def test_kitchen_channel_uses_uuid_string(self) -> None:
        rid = uuid4()
        assert str(rid) in kitchen_channel(rid)

    def test_session_channel_uses_both_uuids(self) -> None:
        rid, sid = uuid4(), uuid4()
        ch = session_channel(rid, sid)
        assert str(rid) in ch
        assert str(sid) in ch


# ---------------------------------------------------------------------------
# Event type constants
# ---------------------------------------------------------------------------


class TestEventTypes:
    """All expected event types are defined."""

    def test_order_created(self) -> None:
        assert EventTypes.ORDER_CREATED == "order.created"

    def test_item_updated(self) -> None:
        assert EventTypes.ITEM_UPDATED == "item.updated"

    def test_item_cancelled(self) -> None:
        assert EventTypes.ITEM_CANCELLED == "item.cancelled"

    def test_staff_call_new(self) -> None:
        assert EventTypes.STAFF_CALL_NEW == "staff_call.new"

    def test_staff_call_ack(self) -> None:
        assert EventTypes.STAFF_CALL_ACK == "staff_call.ack"

    def test_session_closed(self) -> None:
        assert EventTypes.SESSION_CLOSED == "session.closed"

    def test_session_abandoned(self) -> None:
        assert EventTypes.SESSION_ABANDONED == "session.abandoned"


# ---------------------------------------------------------------------------
# RealtimePublisher.publish
# ---------------------------------------------------------------------------


@pytest.fixture
async def redis_client() -> fakeredis_aio.FakeRedis:
    """Provide a fake async Redis client for testing."""
    client = fakeredis_aio.FakeRedis(decode_responses=True)
    yield client  # type: ignore[misc]
    await client.aclose()


class TestRealtimePublisher:
    """RealtimePublisher.publish serializes JSON and publishes to Redis."""

    async def test_publish_sends_json_to_channel(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Verify the message is serialized as JSON and published."""
        channel = kitchen_channel(RID)
        payload = {"item": {"id": "abc", "status": "cooking"}}

        # Subscribe to verify message delivery
        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        # Consume the subscription confirmation message
        await pubsub.get_message(timeout=1)

        await RealtimePublisher.publish(
            channel, EventTypes.ITEM_UPDATED, payload, redis_client
        )

        msg = await pubsub.get_message(timeout=1)
        assert msg is not None
        assert msg["type"] == "message"
        assert msg["channel"] == channel

        data = json.loads(msg["data"])
        assert data["type"] == EventTypes.ITEM_UPDATED
        assert data["item"] == {"id": "abc", "status": "cooking"}
        assert "seq" in data
        assert isinstance(data["seq"], int)

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()

    async def test_publish_merges_payload_with_type(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """The published JSON contains type + seq + all payload keys."""
        channel = session_channel(RID, SID)
        payload = {"order": {"id": "order-1"}, "table": 5}

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1)

        await RealtimePublisher.publish(
            channel, EventTypes.ORDER_CREATED, payload, redis_client
        )

        msg = await pubsub.get_message(timeout=1)
        data = json.loads(msg["data"])
        assert data["type"] == "order.created"
        assert data["order"] == {"id": "order-1"}
        assert data["table"] == 5
        assert "seq" in data
        assert isinstance(data["seq"], int)

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()

    async def test_publish_error_is_logged_not_raised(self) -> None:
        """If Redis publish fails, the error is logged but not raised."""
        broken_client = AsyncMock(spec=["publish"])
        broken_client.publish.side_effect = ConnectionError("Redis down")

        channel = kitchen_channel(RID)

        with patch("qorder_api.realtime.logger") as mock_logger:
            # Should NOT raise
            await RealtimePublisher.publish(
                channel, EventTypes.ITEM_UPDATED, {"x": 1}, broken_client
            )
            mock_logger.exception.assert_called_once()

    async def test_publish_empty_payload(
        self, redis_client: fakeredis_aio.FakeRedis
    ) -> None:
        """Publishing with an empty payload still includes type and seq fields."""
        channel = kitchen_channel(RID)

        pubsub = redis_client.pubsub()
        await pubsub.subscribe(channel)
        await pubsub.get_message(timeout=1)

        await RealtimePublisher.publish(
            channel, EventTypes.SESSION_CLOSED, {}, redis_client
        )

        msg = await pubsub.get_message(timeout=1)
        data = json.loads(msg["data"])
        assert data["type"] == "session.closed"
        assert "seq" in data
        assert isinstance(data["seq"], int)
        # Only type and seq should be present for empty payload
        assert set(data.keys()) == {"type", "seq"}

        await pubsub.unsubscribe(channel)
        await pubsub.aclose()
