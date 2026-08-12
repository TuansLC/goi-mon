"""Tests for POST /t/{qr_token}/orders endpoint (R3.3, R3.4, R3.5, R3.6, R6.6).

Validates:
- Successful order creation with multiple items and snapshots.
- Reject empty cart (422 via Pydantic validation).
- Reject unavailable item (400).
- Reject order on closed/abandoned session (400).
- Verify snapshots match menu item values at order time.
- Verify session.last_activity_at is updated.
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
def app():
    from qorder_api.main import app as _app

    return _app


# ---------- Helpers ----------


def _make_table(
    restaurant_id: uuid.UUID,
    qr_token: str = "order-token-123",
    is_active: bool = True,
) -> MagicMock:
    table = MagicMock()
    table.id = uuid.uuid4()
    table.restaurant_id = restaurant_id
    table.table_number = "B2"
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


def _make_menu_item(
    restaurant_id: uuid.UUID,
    name: str = "Phở bò",
    price: Decimal = Decimal("50000"),
    prep_time_minutes: int = 10,
    is_available: bool = True,
    is_active: bool = True,
    item_id: uuid.UUID | None = None,
) -> MagicMock:
    item = MagicMock()
    item.id = item_id or uuid.uuid4()
    item.restaurant_id = restaurant_id
    item.name = name
    item.price = price
    item.prep_time_minutes = prep_time_minutes
    item.is_available = is_available
    item.is_active = is_active
    return item


def _make_order_item(
    restaurant_id: uuid.UUID,
    order_id: uuid.UUID,
    menu_item: MagicMock,
    quantity: int = 1,
    note: str | None = None,
) -> MagicMock:
    from qorder_api.models.enums import OrderItemStatus

    oi = MagicMock()
    oi.id = uuid.uuid4()
    oi.restaurant_id = restaurant_id
    oi.order_id = order_id
    oi.menu_item_id = menu_item.id
    oi.name_snapshot = menu_item.name
    oi.price_snapshot = menu_item.price
    oi.prep_time_snapshot = menu_item.prep_time_minutes
    oi.quantity = quantity
    oi.note = note
    oi.status = OrderItemStatus.PENDING
    oi.requested_at = datetime.now(timezone.utc)
    oi.served_at = None
    oi.cancelled_at = None
    oi.cancelled_by = None
    oi.cancel_reason = None
    return oi


# ---------- Tests ----------


class TestCreateOrderEndpoint:
    """Test POST /t/{qr_token}/orders."""

    async def test_successful_order_creation(self, app, restaurant_id):
        """A valid order with multiple items creates order + order_items (R3.3, R3.4)."""
        from qorder_api.db import get_session as _gs
        from qorder_api.models.enums import OrderItemStatus
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id, status="open")

        item1 = _make_menu_item(restaurant_id, name="Phở bò", price=Decimal("50000"), prep_time_minutes=10)
        item2 = _make_menu_item(restaurant_id, name="Bún chả", price=Decimal("45000"), prep_time_minutes=8)

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
            elif call_count == 3:  # MenuItem lookup #1
                result.scalar_one_or_none.return_value = item1
            elif call_count == 4:  # MenuItem lookup #2
                result.scalar_one_or_none.return_value = item2
            return result

        mock_session.execute = _mock_execute
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        # Simulate DB-generated defaults on refresh
        async def _mock_refresh(obj):
            from qorder_api.models.order import Order, OrderItem
            if isinstance(obj, Order):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                if obj.created_at is None:
                    obj.created_at = datetime.now(timezone.utc)
            elif isinstance(obj, OrderItem):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                if obj.status is None:
                    obj.status = OrderItemStatus.PENDING

        mock_session.refresh = _mock_refresh

        # Track added objects
        added_objects = []

        def _mock_add(obj):
            added_objects.append(obj)

        mock_session.add = _mock_add

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with patch.object(SessionService, "get_or_open", return_value=table_session):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/t/order-token-123/orders",
                    json={
                        "items": [
                            {"menu_item_id": str(item1.id), "quantity": 2, "note": "ít đá"},
                            {"menu_item_id": str(item2.id), "quantity": 1, "note": None},
                        ]
                    },
                )

        assert resp.status_code == 201
        data = resp.json()
        assert "id" in data
        assert "items" in data
        assert len(data["items"]) == 2

        # Verify snapshots
        assert data["items"][0]["name_snapshot"] == "Phở bò"
        assert Decimal(data["items"][0]["price_snapshot"]) == Decimal("50000")
        assert data["items"][0]["prep_time_snapshot"] == 10
        assert data["items"][0]["quantity"] == 2
        assert data["items"][0]["note"] == "ít đá"
        assert data["items"][0]["status"] == "pending"

        assert data["items"][1]["name_snapshot"] == "Bún chả"
        assert Decimal(data["items"][1]["price_snapshot"]) == Decimal("45000")
        assert data["items"][1]["prep_time_snapshot"] == 8
        assert data["items"][1]["quantity"] == 1

        app.dependency_overrides.clear()

    async def test_reject_empty_cart(self, app, restaurant_id):
        """Empty items list returns 422 (Pydantic validation) (R3.6)."""
        from qorder_api.db import get_session as _gs

        mock_session = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/t/order-token-123/orders",
                json={"items": []},
            )

        assert resp.status_code == 422
        app.dependency_overrides.clear()

    async def test_reject_unavailable_item(self, app, restaurant_id):
        """Ordering an unavailable item returns 400 with item name (R3.2)."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id, status="open")

        unavailable_item = _make_menu_item(
            restaurant_id, name="Bò lúc lắc", is_available=False
        )

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:  # Table
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:  # Restaurant
                result.scalar_one_or_none.return_value = restaurant
            elif call_count == 3:  # MenuItem lookup — found but unavailable
                result.scalar_one_or_none.return_value = unavailable_item
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
                    "/t/order-token-123/orders",
                    json={
                        "items": [
                            {"menu_item_id": str(unavailable_item.id), "quantity": 1},
                        ]
                    },
                )

        assert resp.status_code == 400
        assert "Bò lúc lắc" in resp.json()["detail"]
        assert "hết" in resp.json()["detail"]
        app.dependency_overrides.clear()

    async def test_reject_nonexistent_item(self, app, restaurant_id):
        """Ordering a non-existent menu item returns 400."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id, status="open")

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
            elif call_count == 3:  # MenuItem not found
                result.scalar_one_or_none.return_value = None
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        fake_id = str(uuid.uuid4())
        with patch.object(SessionService, "get_or_open", return_value=table_session):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/t/order-token-123/orders",
                    json={
                        "items": [
                            {"menu_item_id": fake_id, "quantity": 1},
                        ]
                    },
                )

        assert resp.status_code == 400
        assert "không tồn tại" in resp.json()["detail"]
        app.dependency_overrides.clear()

    async def test_reject_closed_session(self, app, restaurant_id):
        """Ordering on a closed session returns 400 (R6.6)."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        closed_session = _make_session(restaurant_id, table.id, status="closed")

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
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        item_id = str(uuid.uuid4())
        with patch.object(SessionService, "get_or_open", return_value=closed_session):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/t/order-token-123/orders",
                    json={
                        "items": [
                            {"menu_item_id": item_id, "quantity": 1},
                        ]
                    },
                )

        assert resp.status_code == 400
        assert "đóng" in resp.json()["detail"]
        app.dependency_overrides.clear()

    async def test_reject_abandoned_session(self, app, restaurant_id):
        """Ordering on an abandoned session returns 400 (R6.6)."""
        from qorder_api.db import get_session as _gs
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        abandoned_session = _make_session(restaurant_id, table.id, status="abandoned")

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
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        item_id = str(uuid.uuid4())
        with patch.object(SessionService, "get_or_open", return_value=abandoned_session):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/t/order-token-123/orders",
                    json={
                        "items": [
                            {"menu_item_id": item_id, "quantity": 1},
                        ]
                    },
                )

        assert resp.status_code == 400
        assert "đóng" in resp.json()["detail"]
        app.dependency_overrides.clear()

    async def test_snapshots_are_correct(self, app, restaurant_id):
        """Verify order item snapshots match menu item values at time of order."""
        from qorder_api.db import get_session as _gs
        from qorder_api.models.enums import OrderItemStatus
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id, status="open")

        item = _make_menu_item(
            restaurant_id,
            name="Cơm tấm sườn",
            price=Decimal("65000"),
            prep_time_minutes=15,
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
                result.scalar_one_or_none.return_value = item
            return result

        mock_session.execute = _mock_execute
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        async def _mock_refresh(obj):
            from qorder_api.models.order import Order, OrderItem
            if isinstance(obj, Order):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                if obj.created_at is None:
                    obj.created_at = datetime.now(timezone.utc)
            elif isinstance(obj, OrderItem):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                if obj.status is None:
                    obj.status = OrderItemStatus.PENDING

        mock_session.refresh = _mock_refresh
        mock_session.add = MagicMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with patch.object(SessionService, "get_or_open", return_value=table_session):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/t/order-token-123/orders",
                    json={
                        "items": [
                            {"menu_item_id": str(item.id), "quantity": 3, "note": "không cay"},
                        ]
                    },
                )

        assert resp.status_code == 201
        data = resp.json()
        order_item = data["items"][0]
        assert order_item["name_snapshot"] == "Cơm tấm sườn"
        assert Decimal(order_item["price_snapshot"]) == Decimal("65000")
        assert order_item["prep_time_snapshot"] == 15
        assert order_item["quantity"] == 3
        assert order_item["note"] == "không cay"
        app.dependency_overrides.clear()

    async def test_last_activity_at_updated(self, app, restaurant_id):
        """Creating an order updates session.last_activity_at."""
        from qorder_api.db import get_session as _gs
        from qorder_api.models.enums import OrderItemStatus
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id, status="open")
        original_activity = table_session.last_activity_at

        item = _make_menu_item(restaurant_id)

        mock_session = AsyncMock()
        call_count = 0
        added_objects = []

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:
                result.scalar_one_or_none.return_value = restaurant
            elif call_count == 3:
                result.scalar_one_or_none.return_value = item
            return result

        mock_session.execute = _mock_execute
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        async def _mock_refresh(obj):
            from qorder_api.models.order import Order, OrderItem
            if isinstance(obj, Order):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                if obj.created_at is None:
                    obj.created_at = datetime.now(timezone.utc)
            elif isinstance(obj, OrderItem):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                if obj.status is None:
                    obj.status = OrderItemStatus.PENDING

        mock_session.refresh = _mock_refresh

        def _mock_add(obj):
            added_objects.append(obj)

        mock_session.add = _mock_add

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with patch.object(SessionService, "get_or_open", return_value=table_session):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/t/order-token-123/orders",
                    json={
                        "items": [
                            {"menu_item_id": str(item.id), "quantity": 1},
                        ]
                    },
                )

        assert resp.status_code == 201
        # last_activity_at should have been updated (is now later than original)
        assert table_session.last_activity_at != original_activity
        assert table_session.last_activity_at > original_activity
        app.dependency_overrides.clear()

    async def test_note_is_optional(self, app, restaurant_id):
        """Note field is optional — omitting it should work (R3.5)."""
        from qorder_api.db import get_session as _gs
        from qorder_api.models.enums import OrderItemStatus
        from qorder_api.services.session_service import SessionService

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        table_session = _make_session(restaurant_id, table.id, status="open")

        item = _make_menu_item(restaurant_id, name="Trà đá")

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
                result.scalar_one_or_none.return_value = item
            return result

        mock_session.execute = _mock_execute
        mock_session.flush = AsyncMock()
        mock_session.commit = AsyncMock()

        async def _mock_refresh(obj):
            from qorder_api.models.order import Order, OrderItem
            if isinstance(obj, Order):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                if obj.created_at is None:
                    obj.created_at = datetime.now(timezone.utc)
            elif isinstance(obj, OrderItem):
                if obj.id is None:
                    obj.id = uuid.uuid4()
                if obj.status is None:
                    obj.status = OrderItemStatus.PENDING

        mock_session.refresh = _mock_refresh
        mock_session.add = MagicMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with patch.object(SessionService, "get_or_open", return_value=table_session):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/t/order-token-123/orders",
                    json={
                        "items": [
                            {"menu_item_id": str(item.id), "quantity": 1},
                        ]
                    },
                )

        assert resp.status_code == 201
        assert resp.json()["items"][0]["note"] is None
        app.dependency_overrides.clear()

    async def test_invalid_quantity_rejected(self, app, restaurant_id):
        """Quantity <= 0 is rejected with 422."""
        from qorder_api.db import get_session as _gs

        mock_session = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/t/order-token-123/orders",
                json={
                    "items": [
                        {"menu_item_id": str(uuid.uuid4()), "quantity": 0},
                    ]
                },
            )

        assert resp.status_code == 422
        app.dependency_overrides.clear()
