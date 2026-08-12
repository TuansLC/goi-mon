"""Tests for staff call cooldown (Property 7, R7.4).

**Validates: Requirements 7.4**

Verifies that for a given table, two staff_calls within the cooldown window
(default 60s) result in only one call being created, calls after the cooldown
expires are allowed, and cooldown is independent between different tables.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qorder_api.models.enums import SessionStatus, StaffCallStatus


# ---------- Fixtures ----------


@pytest.fixture
def restaurant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def app():
    from qorder_api.main import app as _app

    return _app


# ---------- Helpers ----------


def _make_table(
    restaurant_id: uuid.UUID,
    qr_token: str = "call-token-A",
    is_active: bool = True,
) -> MagicMock:
    table = MagicMock()
    table.id = uuid.uuid4()
    table.restaurant_id = restaurant_id
    table.table_number = "A1"
    table.qr_token = qr_token
    table.is_active = is_active
    table.created_at = datetime(2024, 1, 1)
    return table


def _make_restaurant(
    restaurant_id: uuid.UUID,
    is_active: bool = True,
) -> MagicMock:
    settings = MagicMock()
    settings.currency = "VND"
    settings.logo_url = None

    restaurant = MagicMock()
    restaurant.id = restaurant_id
    restaurant.slug = "quan-test"
    restaurant.name = "Quán Test"
    restaurant.is_active = is_active
    restaurant.settings = settings
    return restaurant


def _make_session(
    restaurant_id: uuid.UUID,
    table_id: uuid.UUID,
) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.restaurant_id = restaurant_id
    s.table_id = table_id
    s.status = SessionStatus.OPEN
    s.opened_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    s.last_activity_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    return s


def _make_staff_call(
    restaurant_id: uuid.UUID,
    table_id: uuid.UUID,
    table_session_id: uuid.UUID,
) -> MagicMock:
    call = MagicMock()
    call.id = uuid.uuid4()
    call.restaurant_id = restaurant_id
    call.table_id = table_id
    call.table_session_id = table_session_id
    call.status = StaffCallStatus.PENDING
    call.created_at = datetime.now(timezone.utc)
    call.acknowledged_at = None
    call.acknowledged_by = None
    return call


# ---------- Tests ----------


class TestStaffCallCooldown:
    """Test cooldown behavior for POST /t/{qr_token}/call (R7.4)."""

    async def test_two_calls_within_cooldown_only_one_created(
        self, app, restaurant_id
    ):
        """Two calls within <60s for same table → only 1 call created (200 on 2nd)."""
        from qorder_api.db import get_session as _gs
        from qorder_api.redis import get_redis as _gr

        table = _make_table(restaurant_id, qr_token="cooldown-token")
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id)
        staff_call = _make_staff_call(
            restaurant_id, table.id, table_session.id
        )

        # First call: StaffCallService.create returns a call (success)
        # Second call: StaffCallService.create returns None (within cooldown)
        call_results = iter([staff_call, None])

        with patch(
            "qorder_api.api.customer_router.StaffCallService.create",
            new_callable=AsyncMock,
        ) as mock_create, patch(
            "qorder_api.api.customer_router.SessionService.get_or_open",
            new_callable=AsyncMock,
            return_value=table_session,
        ):
            mock_create.side_effect = lambda **kwargs: next(call_results)

            mock_session = AsyncMock()
            # Both calls resolve the same table and restaurant
            mock_session.execute = AsyncMock(
                side_effect=self._table_restaurant_executor(table, restaurant)
            )

            mock_redis = AsyncMock()

            async def _override_session():
                yield mock_session

            async def _override_redis():
                yield mock_redis

            app.dependency_overrides[_gs] = _override_session
            app.dependency_overrides[_gr] = _override_redis

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                # First call → 201 (created)
                resp1 = await ac.post("/t/cooldown-token/call")
                assert resp1.status_code == 201
                data1 = resp1.json()
                assert data1["status"] == "pending"

                # Second call → 200 (within cooldown)
                resp2 = await ac.post("/t/cooldown-token/call")
                assert resp2.status_code == 200
                data2 = resp2.json()
                assert data2["cooldown"] is True
                assert "message" in data2

            # Verify create was called twice but only first succeeded
            assert mock_create.call_count == 2

        app.dependency_overrides.clear()

    async def test_call_after_cooldown_expired_creates_new_call(
        self, app, restaurant_id
    ):
        """Call after cooldown (>60s) → new call created (201 both times)."""
        from qorder_api.db import get_session as _gs
        from qorder_api.redis import get_redis as _gr

        table = _make_table(restaurant_id, qr_token="expired-token")
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id)

        call_1 = _make_staff_call(restaurant_id, table.id, table_session.id)
        call_2 = _make_staff_call(restaurant_id, table.id, table_session.id)

        # Both calls succeed (cooldown has expired between them)
        call_results = iter([call_1, call_2])

        with patch(
            "qorder_api.api.customer_router.StaffCallService.create",
            new_callable=AsyncMock,
        ) as mock_create, patch(
            "qorder_api.api.customer_router.SessionService.get_or_open",
            new_callable=AsyncMock,
            return_value=table_session,
        ):
            mock_create.side_effect = lambda **kwargs: next(call_results)

            mock_session = AsyncMock()
            mock_session.execute = AsyncMock(
                side_effect=self._table_restaurant_executor(table, restaurant)
            )

            mock_redis = AsyncMock()

            async def _override_session():
                yield mock_session

            async def _override_redis():
                yield mock_redis

            app.dependency_overrides[_gs] = _override_session
            app.dependency_overrides[_gr] = _override_redis

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                # First call → 201
                resp1 = await ac.post("/t/expired-token/call")
                assert resp1.status_code == 201

                # Second call → 201 (cooldown expired, service returns new call)
                resp2 = await ac.post("/t/expired-token/call")
                assert resp2.status_code == 201

            # Both calls created successfully
            assert mock_create.call_count == 2

        app.dependency_overrides.clear()

    async def test_cooldown_independent_between_tables(
        self, app, restaurant_id
    ):
        """Cooldown is per-table: calling on table B immediately after A → 201."""
        from qorder_api.db import get_session as _gs
        from qorder_api.redis import get_redis as _gr

        table_a = _make_table(restaurant_id, qr_token="table-a-token")
        table_b = _make_table(restaurant_id, qr_token="table-b-token")
        restaurant = _make_restaurant(restaurant_id)
        session_a = _make_session(restaurant_id, table_a.id)
        session_b = _make_session(restaurant_id, table_b.id)

        call_a = _make_staff_call(restaurant_id, table_a.id, session_a.id)
        call_b = _make_staff_call(restaurant_id, table_b.id, session_b.id)

        # Track which table is being called to return appropriate session/call
        create_calls = []

        async def _mock_create(**kwargs):
            create_calls.append(kwargs["table_id"])
            if kwargs["table_id"] == table_a.id:
                return call_a
            return call_b

        session_map = {table_a.id: session_a, table_b.id: session_b}

        async def _mock_get_or_open(table_id, restaurant_id, session):
            return session_map[table_id]

        with patch(
            "qorder_api.api.customer_router.StaffCallService.create",
            new_callable=AsyncMock,
            side_effect=_mock_create,
        ) as mock_create, patch(
            "qorder_api.api.customer_router.SessionService.get_or_open",
            new_callable=AsyncMock,
            side_effect=_mock_get_or_open,
        ):
            mock_session = AsyncMock()
            call_count = {"value": 0}

            async def _mock_execute(stmt):
                call_count["value"] += 1
                result = MagicMock()
                idx = call_count["value"]
                # Calls alternate: table lookup, restaurant lookup for each request
                if idx == 1:  # Table A lookup
                    result.scalar_one_or_none.return_value = table_a
                elif idx == 2:  # Restaurant lookup for A
                    result.scalar_one_or_none.return_value = restaurant
                elif idx == 3:  # Table B lookup
                    result.scalar_one_or_none.return_value = table_b
                elif idx == 4:  # Restaurant lookup for B
                    result.scalar_one_or_none.return_value = restaurant
                return result

            mock_session.execute = AsyncMock(side_effect=_mock_execute)
            mock_redis = AsyncMock()

            async def _override_session():
                yield mock_session

            async def _override_redis():
                yield mock_redis

            app.dependency_overrides[_gs] = _override_session
            app.dependency_overrides[_gr] = _override_redis

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                # Call table A → 201
                resp_a = await ac.post("/t/table-a-token/call")
                assert resp_a.status_code == 201

                # Call table B immediately → 201 (different table, independent)
                resp_b = await ac.post("/t/table-b-token/call")
                assert resp_b.status_code == 201

            # Both tables got their calls
            assert mock_create.call_count == 2
            assert table_a.id in create_calls
            assert table_b.id in create_calls

        app.dependency_overrides.clear()

    # ---------- Helper ----------

    @staticmethod
    def _table_restaurant_executor(table, restaurant):
        """Return a side_effect function that alternates table/restaurant lookups."""
        call_count = {"value": 0}

        async def _execute(stmt):
            call_count["value"] += 1
            result = MagicMock()
            # Odd calls = table lookup, even calls = restaurant lookup
            if call_count["value"] % 2 == 1:
                result.scalar_one_or_none.return_value = table
            else:
                result.scalar_one_or_none.return_value = restaurant
            return result

        return _execute
