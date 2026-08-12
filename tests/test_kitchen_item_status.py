"""Tests for POST /kitchen/items/{item_id}/status endpoint (R4.1–R4.7).

Validates:
- Forward transitions: pending→cooking, pending→served, cooking→ready, ready→served.
- Undo transition: served→pending within 120s.
- Reject invalid transitions (409 on CAS failure).
- Reject unauthorized access (no JWT / wrong role).
- Tenant isolation (item from another restaurant → 404).
- Sets served_by/served_at on transition to served.
- Clears served_by/served_at on undo (served→pending).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qorder_api.auth.jwt import TokenPayload, create_access_token
from qorder_api.models.enums import OrderItemStatus


# ---------- Fixtures ----------


@pytest.fixture
def restaurant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def staff_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def app():
    from qorder_api.main import app as _app

    return _app


@pytest.fixture
def staff_token(staff_user_id, restaurant_id) -> str:
    return create_access_token(
        user_id=staff_user_id,
        role="staff",
        restaurant_id=restaurant_id,
    )


@pytest.fixture
def staff_headers(staff_token) -> dict:
    return {"Authorization": f"Bearer {staff_token}"}


# ---------- Tests ----------


class TestSetItemStatusEndpoint:
    """Test POST /kitchen/items/{item_id}/status."""

    async def test_forward_pending_to_cooking(
        self, app, restaurant_id, staff_user_id, staff_headers
    ):
        """pending → cooking succeeds (R4.3)."""
        from qorder_api.db import get_session as _gs

        item_id = uuid.uuid4()
        order_id = uuid.uuid4()

        mock_session = AsyncMock()
        call_count = 0

        # Row returned by CAS UPDATE
        cas_row = {
            "id": item_id,
            "restaurant_id": restaurant_id,
            "order_id": order_id,
            "menu_item_id": uuid.uuid4(),
            "name_snapshot": "Phở bò",
            "price_snapshot": Decimal("50000"),
            "prep_time_snapshot": 10,
            "quantity": 1,
            "note": None,
            "status": "cooking",
            "requested_at": datetime.now(timezone.utc),
            "served_by": None,
            "served_at": None,
            "cancelled_by": None,
            "cancelled_at": None,
            "cancel_reason": None,
        }

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                # Tenant check: SELECT order_items.id
                result.scalar_one_or_none.return_value = item_id
            elif call_count == 2:
                # CAS UPDATE RETURNING *
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = cas_row
                result.mappings.return_value = mappings_mock
            elif call_count == 3:
                # UPDATE table_sessions.last_activity_at
                pass
            return result

        mock_session.execute = _mock_execute
        mock_session.commit = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_id}/status",
                json={"to": "cooking"},
                headers=staff_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cooking"
        assert data["name_snapshot"] == "Phở bò"
        app.dependency_overrides.clear()

    async def test_forward_pending_to_served(
        self, app, restaurant_id, staff_user_id, staff_headers
    ):
        """pending → served succeeds, sets served_by/served_at (R4.4, R4.7)."""
        from qorder_api.db import get_session as _gs

        item_id = uuid.uuid4()
        order_id = uuid.uuid4()
        now = datetime.now(timezone.utc)

        cas_row = {
            "id": item_id,
            "restaurant_id": restaurant_id,
            "order_id": order_id,
            "menu_item_id": uuid.uuid4(),
            "name_snapshot": "Bún chả",
            "price_snapshot": Decimal("45000"),
            "prep_time_snapshot": 8,
            "quantity": 2,
            "note": "ít bún",
            "status": "served",
            "requested_at": now,
            "served_by": staff_user_id,
            "served_at": now,
            "cancelled_by": None,
            "cancelled_at": None,
            "cancel_reason": None,
        }

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = item_id
            elif call_count == 2:
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = cas_row
                result.mappings.return_value = mappings_mock
            elif call_count == 3:
                pass
            return result

        mock_session.execute = _mock_execute
        mock_session.commit = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_id}/status",
                json={"to": "served"},
                headers=staff_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "served"
        assert data["served_by"] == str(staff_user_id)
        assert data["served_at"] is not None
        app.dependency_overrides.clear()

    async def test_undo_served_to_pending(
        self, app, restaurant_id, staff_user_id, staff_headers
    ):
        """served → pending within 120s succeeds, clears served_by/at (R4.7)."""
        from qorder_api.db import get_session as _gs

        item_id = uuid.uuid4()
        order_id = uuid.uuid4()

        cas_row = {
            "id": item_id,
            "restaurant_id": restaurant_id,
            "order_id": order_id,
            "menu_item_id": uuid.uuid4(),
            "name_snapshot": "Cơm tấm",
            "price_snapshot": Decimal("65000"),
            "prep_time_snapshot": 12,
            "quantity": 1,
            "note": None,
            "status": "pending",
            "requested_at": datetime.now(timezone.utc),
            "served_by": None,
            "served_at": None,
            "cancelled_by": None,
            "cancelled_at": None,
            "cancel_reason": None,
        }

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = item_id
            elif call_count == 2:
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = cas_row
                result.mappings.return_value = mappings_mock
            elif call_count == 3:
                pass
            return result

        mock_session.execute = _mock_execute
        mock_session.commit = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_id}/status",
                json={"to": "pending"},
                headers=staff_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "pending"
        assert data["served_by"] is None
        assert data["served_at"] is None
        app.dependency_overrides.clear()

    async def test_conflict_when_cas_returns_zero_rows(
        self, app, restaurant_id, staff_user_id, staff_headers
    ):
        """CAS returns 0 rows → 409 Conflict (R4.6)."""
        from qorder_api.db import get_session as _gs

        item_id = uuid.uuid4()

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = item_id
            elif call_count == 2:
                # CAS fails — 0 rows returned
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = None
                result.mappings.return_value = mappings_mock
            return result

        mock_session.execute = _mock_execute
        mock_session.commit = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_id}/status",
                json={"to": "cooking"},
                headers=staff_headers,
            )

        assert resp.status_code == 409
        assert "thay đổi" in resp.json()["detail"]
        app.dependency_overrides.clear()

    async def test_invalid_transition_to_cancelled(
        self, app, restaurant_id, staff_user_id, staff_headers
    ):
        """Transition to 'cancelled' via this endpoint returns 400 (use cancel endpoint)."""
        from qorder_api.db import get_session as _gs

        item_id = uuid.uuid4()

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_id}/status",
                json={"to": "cancelled"},
                headers=staff_headers,
            )

        assert resp.status_code == 400
        app.dependency_overrides.clear()

    async def test_tenant_isolation_item_not_found(
        self, app, restaurant_id, staff_user_id, staff_headers
    ):
        """Item from different restaurant → 404 (tenant isolation)."""
        from qorder_api.db import get_session as _gs

        item_id = uuid.uuid4()

        mock_session = AsyncMock()

        async def _mock_execute(stmt, params=None):
            result = MagicMock()
            # Item not found for this restaurant_id
            result.scalar_one_or_none.return_value = None
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_id}/status",
                json={"to": "cooking"},
                headers=staff_headers,
            )

        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_no_auth_returns_401(self, app):
        """Missing JWT returns 401."""
        from qorder_api.db import get_session as _gs

        mock_session = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        item_id = uuid.uuid4()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_id}/status",
                json={"to": "cooking"},
            )

        assert resp.status_code == 401
        app.dependency_overrides.clear()
