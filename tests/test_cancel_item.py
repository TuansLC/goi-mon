"""Tests for cancel item endpoints (R11.1–R11.7).

Validates:
- Customer cancels pending item → success (R11.2)
- Customer tries to cancel cooking item → 409 (R11.3)
- Staff cancels cooking item → success (R11.4)
- Staff cancels ready item → success (R11.4)
- Both fail on already-served item → 409
- Both fail on already-cancelled item → 409
- Customer can only cancel items from their own session (via qr_token)
- Tenant isolation for staff cancel
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest


# ---------- Fixtures ----------


@pytest.fixture
def restaurant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def other_restaurant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def app():
    from qorder_api.main import app as _app

    return _app


# ---------- Helpers ----------


def _make_table(
    restaurant_id: uuid.UUID,
    qr_token: str = "cancel-token-123",
    is_active: bool = True,
) -> MagicMock:
    table = MagicMock()
    table.id = uuid.uuid4()
    table.restaurant_id = restaurant_id
    table.table_number = "B5"
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
    status: str = "open",
) -> MagicMock:
    from qorder_api.models.enums import SessionStatus

    s = MagicMock()
    s.id = uuid.uuid4()
    s.restaurant_id = restaurant_id
    s.table_id = table_id
    s.status = SessionStatus(status)
    s.opened_by = None
    s.opened_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    s.last_activity_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    s.closed_at = None
    s.abandoned_at = None
    s.total_amount = None
    return s


def _make_cancelled_order_item(
    restaurant_id: uuid.UUID,
    order_id: uuid.UUID,
    cancelled_by: str = "customer",
    cancel_reason: str | None = None,
    item_id: uuid.UUID | None = None,
) -> MagicMock:
    from qorder_api.models.enums import CancelledBy, OrderItemStatus

    oi = MagicMock()
    oi.id = item_id or uuid.uuid4()
    oi.restaurant_id = restaurant_id
    oi.order_id = order_id
    oi.menu_item_id = uuid.uuid4()
    oi.name_snapshot = "Phở bò"
    oi.price_snapshot = Decimal("50000")
    oi.prep_time_snapshot = 10
    oi.quantity = 1
    oi.note = None
    oi.status = OrderItemStatus.CANCELLED
    oi.requested_at = datetime.now(timezone.utc)
    oi.served_by = None
    oi.served_at = None
    oi.cancelled_by = CancelledBy(cancelled_by)
    oi.cancelled_at = datetime.now(timezone.utc)
    oi.cancel_reason = cancel_reason
    return oi


def _make_staff_user(restaurant_id: uuid.UUID) -> MagicMock:
    """Create a mock TokenPayload for staff."""
    user = MagicMock()
    user.sub = uuid.uuid4()
    user.restaurant_id = restaurant_id
    user.role = "staff"
    return user


# ---------- Tests: Customer cancel ----------


class TestCustomerCancelItem:
    """Test POST /t/{qr_token}/items/{item_id}/cancel (customer)."""

    async def test_customer_cancels_pending_item_success(self, app, restaurant_id):
        """Customer can cancel a pending item → 200 with cancelled status (R11.2)."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import ItemStateService
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id)
        item_id = uuid.uuid4()
        order_id = uuid.uuid4()

        cancelled_item = _make_cancelled_order_item(
            restaurant_id, order_id, cancelled_by="customer", item_id=item_id
        )

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:  # Table lookup
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:  # Restaurant lookup
                result.scalar_one_or_none.return_value = restaurant
            elif call_count == 3:  # Item belongs to session check
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with (
            patch.object(SessionService, "get_or_open", return_value=table_session),
            patch.object(
                ItemStateService, "cancel_item", return_value=cancelled_item
            ) as mock_cancel,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/t/cancel-token-123/items/{item_id}/cancel",
                    json={"reason": "Gọi nhầm"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancelled_by"] == "customer"
        assert data["id"] == str(item_id)

        # Verify cancel_item was called with correct args
        mock_cancel.assert_called_once()
        call_kwargs = mock_cancel.call_args.kwargs
        assert call_kwargs["item_id"] == item_id
        assert call_kwargs["cancelled_by"].value == "customer"
        assert call_kwargs["cancel_reason"] == "Gọi nhầm"

        app.dependency_overrides.clear()

    async def test_customer_cancel_cooking_item_returns_409(self, app, restaurant_id):
        """Customer cannot cancel a cooking item → 409 (R11.3)."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import (
            ConflictError,
            ItemStateService,
        )
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id)
        item_id = uuid.uuid4()

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:
                result.scalar_one_or_none.return_value = restaurant
            elif call_count == 3:
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with (
            patch.object(SessionService, "get_or_open", return_value=table_session),
            patch.object(
                ItemStateService,
                "cancel_item",
                side_effect=ConflictError(
                    "Không thể huỷ: món đã được phục vụ hoặc đã bị huỷ trước đó."
                ),
            ),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/t/cancel-token-123/items/{item_id}/cancel",
                )

        assert resp.status_code == 409
        assert "huỷ" in resp.json()["detail"]

        app.dependency_overrides.clear()

    async def test_customer_cancel_item_not_in_session_returns_404(
        self, app, restaurant_id
    ):
        """Customer cannot cancel items that don't belong to their session."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id)
        item_id = uuid.uuid4()

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:
                result.scalar_one_or_none.return_value = restaurant
            elif call_count == 3:  # Item NOT found in this session
                result.scalar_one_or_none.return_value = None
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with patch.object(SessionService, "get_or_open", return_value=table_session):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/t/cancel-token-123/items/{item_id}/cancel",
                )

        assert resp.status_code == 404
        assert "phiên" in resp.json()["detail"]

        app.dependency_overrides.clear()

    async def test_customer_cancel_served_item_returns_409(self, app, restaurant_id):
        """Customer cannot cancel a served item → 409."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import (
            ConflictError,
            ItemStateService,
        )
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id)
        item_id = uuid.uuid4()

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:
                result.scalar_one_or_none.return_value = restaurant
            elif call_count == 3:
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with (
            patch.object(SessionService, "get_or_open", return_value=table_session),
            patch.object(
                ItemStateService,
                "cancel_item",
                side_effect=ConflictError(
                    "Không thể huỷ: món đã được phục vụ hoặc đã bị huỷ trước đó."
                ),
            ),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/t/cancel-token-123/items/{item_id}/cancel",
                )

        assert resp.status_code == 409

        app.dependency_overrides.clear()

    async def test_customer_cancel_already_cancelled_returns_409(
        self, app, restaurant_id
    ):
        """Customer cannot cancel an already-cancelled item → 409."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import (
            ConflictError,
            ItemStateService,
        )
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id)
        item_id = uuid.uuid4()

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:
                result.scalar_one_or_none.return_value = restaurant
            elif call_count == 3:
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with (
            patch.object(SessionService, "get_or_open", return_value=table_session),
            patch.object(
                ItemStateService,
                "cancel_item",
                side_effect=ConflictError(
                    "Không thể huỷ: món đã được phục vụ hoặc đã bị huỷ trước đó."
                ),
            ),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/t/cancel-token-123/items/{item_id}/cancel",
                )

        assert resp.status_code == 409

        app.dependency_overrides.clear()

    async def test_customer_cancel_no_body_works(self, app, restaurant_id):
        """Customer cancel without body (no reason) → 200."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import ItemStateService
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id)
        item_id = uuid.uuid4()
        order_id = uuid.uuid4()

        cancelled_item = _make_cancelled_order_item(
            restaurant_id, order_id, cancelled_by="customer", item_id=item_id
        )

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:
                result.scalar_one_or_none.return_value = restaurant
            elif call_count == 3:
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with (
            patch.object(SessionService, "get_or_open", return_value=table_session),
            patch.object(
                ItemStateService, "cancel_item", return_value=cancelled_item
            ) as mock_cancel,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/t/cancel-token-123/items/{item_id}/cancel",
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        # Verify cancel_reason is None when no body
        call_kwargs = mock_cancel.call_args.kwargs
        assert call_kwargs["cancel_reason"] is None

        app.dependency_overrides.clear()


# ---------- Tests: Staff cancel ----------


class TestStaffCancelItem:
    """Test POST /kitchen/items/{item_id}/cancel (staff)."""

    async def test_staff_cancels_cooking_item_success(self, app, restaurant_id):
        """Staff can cancel a cooking item → 200 (R11.4)."""
        from qorder_api.auth.dependencies import get_current_user, require_role
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import ItemStateService

        item_id = uuid.uuid4()
        order_id = uuid.uuid4()
        staff_user = _make_staff_user(restaurant_id)

        cancelled_item = _make_cancelled_order_item(
            restaurant_id, order_id, cancelled_by="staff", item_id=item_id
        )

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:  # Item existence check
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        async def _override_user():
            return staff_user

        async def _override_role(*roles):
            async def _checker(current_user=None):
                return staff_user

            return _checker

        app.dependency_overrides[_gs] = _override_session
        app.dependency_overrides[get_current_user] = _override_user

        with patch.object(
            ItemStateService, "cancel_item", return_value=cancelled_item
        ) as mock_cancel:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/kitchen/items/{item_id}/cancel",
                    json={"reason": "Hết nguyên liệu"},
                    headers={"Authorization": "Bearer fake-token"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "cancelled"
        assert data["cancelled_by"] == "staff"

        mock_cancel.assert_called_once()
        call_kwargs = mock_cancel.call_args.kwargs
        assert call_kwargs["cancelled_by"].value == "staff"
        assert call_kwargs["cancel_reason"] == "Hết nguyên liệu"

        app.dependency_overrides.clear()

    async def test_staff_cancels_ready_item_success(self, app, restaurant_id):
        """Staff can cancel a ready item → 200 (R11.4)."""
        from qorder_api.auth.dependencies import get_current_user
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import ItemStateService

        item_id = uuid.uuid4()
        order_id = uuid.uuid4()
        staff_user = _make_staff_user(restaurant_id)

        cancelled_item = _make_cancelled_order_item(
            restaurant_id, order_id, cancelled_by="staff", item_id=item_id
        )

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        async def _override_user():
            return staff_user

        app.dependency_overrides[_gs] = _override_session
        app.dependency_overrides[get_current_user] = _override_user

        with patch.object(
            ItemStateService, "cancel_item", return_value=cancelled_item
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/kitchen/items/{item_id}/cancel",
                    headers={"Authorization": "Bearer fake-token"},
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        app.dependency_overrides.clear()

    async def test_staff_cancel_served_item_returns_409(self, app, restaurant_id):
        """Staff cannot cancel a served item → 409."""
        from qorder_api.auth.dependencies import get_current_user
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import (
            ConflictError,
            ItemStateService,
        )

        item_id = uuid.uuid4()
        staff_user = _make_staff_user(restaurant_id)

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        async def _override_user():
            return staff_user

        app.dependency_overrides[_gs] = _override_session
        app.dependency_overrides[get_current_user] = _override_user

        with patch.object(
            ItemStateService,
            "cancel_item",
            side_effect=ConflictError(
                "Không thể huỷ: món đã được phục vụ hoặc đã bị huỷ trước đó."
            ),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/kitchen/items/{item_id}/cancel",
                    headers={"Authorization": "Bearer fake-token"},
                )

        assert resp.status_code == 409
        assert "huỷ" in resp.json()["detail"]

        app.dependency_overrides.clear()

    async def test_staff_cancel_already_cancelled_returns_409(
        self, app, restaurant_id
    ):
        """Staff cannot cancel an already-cancelled item → 409."""
        from qorder_api.auth.dependencies import get_current_user
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import (
            ConflictError,
            ItemStateService,
        )

        item_id = uuid.uuid4()
        staff_user = _make_staff_user(restaurant_id)

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        async def _override_user():
            return staff_user

        app.dependency_overrides[_gs] = _override_session
        app.dependency_overrides[get_current_user] = _override_user

        with patch.object(
            ItemStateService,
            "cancel_item",
            side_effect=ConflictError(
                "Không thể huỷ: món đã được phục vụ hoặc đã bị huỷ trước đó."
            ),
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/kitchen/items/{item_id}/cancel",
                    headers={"Authorization": "Bearer fake-token"},
                )

        assert resp.status_code == 409

        app.dependency_overrides.clear()

    async def test_staff_cancel_item_not_found_returns_404(
        self, app, restaurant_id
    ):
        """Staff cancel on non-existent item or different tenant → 404."""
        from qorder_api.auth.dependencies import get_current_user
        from qorder_api.db import get_session as _gs

        item_id = uuid.uuid4()
        staff_user = _make_staff_user(restaurant_id)

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:  # Item not found (wrong restaurant)
                result.scalar_one_or_none.return_value = None
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        async def _override_user():
            return staff_user

        app.dependency_overrides[_gs] = _override_session
        app.dependency_overrides[get_current_user] = _override_user

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_id}/cancel",
                headers={"Authorization": "Bearer fake-token"},
            )

        assert resp.status_code == 404
        assert "không thuộc quán" in resp.json()["detail"]

        app.dependency_overrides.clear()

    async def test_staff_cancel_no_body_works(self, app, restaurant_id):
        """Staff cancel without body (no reason) → 200."""
        from qorder_api.auth.dependencies import get_current_user
        from qorder_api.db import get_session as _gs
        from qorder_api.services.item_state_service import ItemStateService

        item_id = uuid.uuid4()
        order_id = uuid.uuid4()
        staff_user = _make_staff_user(restaurant_id)

        cancelled_item = _make_cancelled_order_item(
            restaurant_id, order_id, cancelled_by="staff", item_id=item_id
        )

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = item_id
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        async def _override_user():
            return staff_user

        app.dependency_overrides[_gs] = _override_session
        app.dependency_overrides[get_current_user] = _override_user

        with patch.object(
            ItemStateService, "cancel_item", return_value=cancelled_item
        ) as mock_cancel:
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/kitchen/items/{item_id}/cancel",
                    headers={"Authorization": "Bearer fake-token"},
                )

        assert resp.status_code == 200
        assert resp.json()["status"] == "cancelled"

        call_kwargs = mock_cancel.call_args.kwargs
        assert call_kwargs["cancel_reason"] is None

        app.dependency_overrides.clear()
