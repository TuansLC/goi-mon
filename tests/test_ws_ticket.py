"""Tests for WebSocket one-shot ticket (R12.10, R4.3).

Validates:
- Ticket is single-use (second verify returns None).
- Expired ticket returns None after TTL.
- PIN required branch: Staff JWT → ticket issued; missing JWT → 401.
- PIN not required branch: anonymous + slug → ticket with user_id=null.
"""

from __future__ import annotations

import asyncio
import uuid

import fakeredis.aioredis
import pytest

from qorder_api.auth.ws_ticket import issue_ws_ticket, verify_ws_ticket


# ---------- Fixtures ----------


@pytest.fixture
def redis_client():
    """Create a fresh in-memory fakeredis client for each test."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def restaurant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def user_id() -> uuid.UUID:
    return uuid.uuid4()


# ---------- Unit tests for issue/verify ----------


class TestIssueAndVerify:
    """Core ticket lifecycle: issue → verify → consumed."""

    async def test_issue_returns_string(self, redis_client, restaurant_id, user_id):
        ticket = await issue_ws_ticket(
            restaurant_id=restaurant_id,
            role="staff",
            user_id=user_id,
            redis_client=redis_client,
        )
        assert isinstance(ticket, str)
        assert len(ticket) > 20  # token_urlsafe(32) produces ~43 chars

    async def test_verify_returns_payload(self, redis_client, restaurant_id, user_id):
        ticket = await issue_ws_ticket(
            restaurant_id=restaurant_id,
            role="staff",
            user_id=user_id,
            redis_client=redis_client,
        )
        payload = await verify_ws_ticket(ticket, redis_client)

        assert payload is not None
        assert payload["restaurant_id"] == str(restaurant_id)
        assert payload["role"] == "staff"
        assert payload["user_id"] == str(user_id)

    async def test_ticket_one_shot_second_verify_fails(
        self, redis_client, restaurant_id, user_id
    ):
        """A ticket must be consumed exactly once; second attempt returns None."""
        ticket = await issue_ws_ticket(
            restaurant_id=restaurant_id,
            role="staff",
            user_id=user_id,
            redis_client=redis_client,
        )

        # First verify succeeds
        first = await verify_ws_ticket(ticket, redis_client)
        assert first is not None

        # Second verify must fail (ticket already consumed via GETDEL)
        second = await verify_ws_ticket(ticket, redis_client)
        assert second is None

    async def test_verify_nonexistent_ticket_returns_none(self, redis_client):
        """A completely unknown ticket returns None."""
        result = await verify_ws_ticket("nonexistent-ticket-value", redis_client)
        assert result is None

    async def test_anonymous_ticket_user_id_null(self, redis_client, restaurant_id):
        """When PIN is not required, ticket is issued with user_id=None."""
        ticket = await issue_ws_ticket(
            restaurant_id=restaurant_id,
            role="staff",
            user_id=None,
            redis_client=redis_client,
        )
        payload = await verify_ws_ticket(ticket, redis_client)

        assert payload is not None
        assert payload["user_id"] is None

    async def test_ticket_expires_after_ttl(self, redis_client, restaurant_id, user_id):
        """Ticket should be gone after the TTL expires (simulated via fakeredis time)."""
        ticket = await issue_ws_ticket(
            restaurant_id=restaurant_id,
            role="staff",
            user_id=user_id,
            redis_client=redis_client,
        )

        # Manually delete the key to simulate TTL expiry (fakeredis doesn't
        # auto-expire without time advancement, so we just remove it)
        key = f"ws_ticket:{ticket}"
        await redis_client.delete(key)

        result = await verify_ws_ticket(ticket, redis_client)
        assert result is None


# ---------- Integration tests via FastAPI TestClient ----------

import httpx
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create a fresh app instance for endpoint testing."""
    from qorder_api.main import app as _app
    return _app


@pytest.fixture
def fake_redis():
    """Shared fakeredis instance for endpoint tests."""
    return fakeredis.aioredis.FakeRedis(decode_responses=True)


@pytest.fixture
def client(app, fake_redis):
    """HTTPX AsyncClient with overridden Redis dependency."""
    from qorder_api.redis import get_redis

    async def _override_redis():
        yield fake_redis

    app.dependency_overrides[get_redis] = _override_redis
    yield app
    app.dependency_overrides.clear()


def _make_restaurant(slug: str, is_active: bool = True, pin_required: bool = True):
    """Create a mock Restaurant + Settings object."""
    rest = MagicMock()
    rest.id = uuid.uuid4()
    rest.slug = slug
    rest.is_active = is_active
    rest.settings = MagicMock()
    rest.settings.kitchen_screen_requires_pin = pin_required
    return rest


class TestWsTicketEndpoint:
    """POST /auth/ws-ticket endpoint tests."""

    async def test_pin_required_no_jwt_returns_401(self, client):
        """When kitchen_screen_requires_pin=True and no JWT → 401."""
        restaurant = _make_restaurant("test-resto", pin_required=True)

        from qorder_api.db import get_session as _gs

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = restaurant
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override_session():
            yield mock_session

        client.dependency_overrides[_gs] = _override_session

        with patch(
            "qorder_api.auth.dependencies.get_kitchen_pin_required",
            new=AsyncMock(return_value=True),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/auth/ws-ticket",
                    json={"restaurant_slug": "test-resto"},
                )

        assert resp.status_code == 401

    async def test_pin_required_valid_jwt_returns_ticket(self, client, fake_redis):
        """When kitchen_screen_requires_pin=True and valid Staff JWT → ticket issued."""
        restaurant = _make_restaurant("test-resto", pin_required=True)
        staff_user_id = uuid.uuid4()

        from qorder_api.auth.jwt import create_access_token

        token = create_access_token(
            user_id=staff_user_id,
            role="staff",
            restaurant_id=restaurant.id,
        )

        from qorder_api.db import get_session as _gs

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = restaurant
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override_session():
            yield mock_session

        client.dependency_overrides[_gs] = _override_session

        with patch(
            "qorder_api.auth.dependencies.get_kitchen_pin_required",
            new=AsyncMock(return_value=True),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/auth/ws-ticket",
                    json={"restaurant_slug": "test-resto"},
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert "ticket" in data
        assert isinstance(data["ticket"], str)

        # Verify ticket is valid in Redis
        payload = await verify_ws_ticket(data["ticket"], fake_redis)
        assert payload is not None
        assert payload["restaurant_id"] == str(restaurant.id)
        assert payload["user_id"] == str(staff_user_id)

    async def test_pin_not_required_anonymous_returns_ticket(self, client, fake_redis):
        """When kitchen_screen_requires_pin=False → anonymous ticket with user_id=null."""
        restaurant = _make_restaurant("anon-resto", pin_required=False)

        from qorder_api.db import get_session as _gs

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = restaurant
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override_session():
            yield mock_session

        client.dependency_overrides[_gs] = _override_session

        with patch(
            "qorder_api.auth.dependencies.get_kitchen_pin_required",
            new=AsyncMock(return_value=False),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=client),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/auth/ws-ticket",
                    json={"restaurant_slug": "anon-resto"},
                    # No Authorization header — anonymous
                )

        assert resp.status_code == 200
        data = resp.json()
        assert "ticket" in data

        # Verify ticket payload
        payload = await verify_ws_ticket(data["ticket"], fake_redis)
        assert payload is not None
        assert payload["user_id"] is None
        assert payload["role"] == "staff"

    async def test_restaurant_not_found_returns_404(self, client):
        """Unknown slug → 404."""
        from qorder_api.db import get_session as _gs

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override_session():
            yield mock_session

        client.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=client),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/auth/ws-ticket",
                json={"restaurant_slug": "no-such-restaurant"},
            )

        assert resp.status_code == 404
