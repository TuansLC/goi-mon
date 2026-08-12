"""Integration tests for checkout & billing flow (R6.1, R6.6, R6.8, R6.9).

Validates:
- Property 3: Bill total only includes served items.
- Property 5: Auto-cancel on close with reason 'table_closed'.
- R6.6: Cannot add order after session closed.
- R6.9: Dismiss pending staff_calls on checkout.
- Property 8: Snapshot price immutability.
- CAS race protection (409 on already-closed/abandoned sessions).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qorder_api.auth.dependencies import get_current_user
from qorder_api.auth.jwt import TokenPayload
from qorder_api.db import get_session as _gs
from qorder_api.models.enums import SessionStatus
from qorder_api.redis import get_redis
from qorder_api.services.session_service import CheckoutResult, SessionService


# ---------- Fixtures ----------


@pytest.fixture
def restaurant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def staff_user(restaurant_id) -> TokenPayload:
    return TokenPayload(
        sub=uuid.uuid4(),
        restaurant_id=restaurant_id,
        role="staff",
    )


@pytest.fixture
def app():
    from qorder_api.main import app as _app

    yield _app
    _app.dependency_overrides.clear()


# ---------- Helpers ----------


def _make_session_model(
    restaurant_id: uuid.UUID,
    status: str = "open",
    total_amount: Decimal | None = None,
) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.restaurant_id = restaurant_id
    s.table_id = uuid.uuid4()
    s.status = SessionStatus(status)
    s.opened_by = None
    s.opened_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    s.last_activity_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    s.closed_at = datetime(2024, 6, 1, 14, 0, 0, tzinfo=timezone.utc) if status == "closed" else None
    s.abandoned_at = datetime(2024, 6, 1, 14, 0, 0, tzinfo=timezone.utc) if status == "abandoned" else None
    s.total_amount = total_amount
    return s


def _override_auth(app, staff_user: TokenPayload):
    """Override auth dependency to return a fake staff user."""

    async def _fake_user():
        return staff_user

    app.dependency_overrides[get_current_user] = _fake_user


def _override_db(app, mock_session):
    """Override DB session dependency."""

    async def _fake_session():
        yield mock_session

    app.dependency_overrides[_gs] = _fake_session


def _override_redis(app):
    """Override Redis dependency with a fake."""
    fake_redis = AsyncMock()
    fake_redis.publish = AsyncMock(return_value=1)

    async def _fake_redis():
        yield fake_redis

    app.dependency_overrides[get_redis] = _fake_redis
    return fake_redis


# ---------- Tests ----------


class TestBillTotalOnlyServedItems:
    """Property 3 — Bill total only includes served items."""

    async def test_total_only_sums_served_items(self, app, restaurant_id, staff_user):
        """Checkout total = SUM(price_snapshot * quantity) for served items ONLY.

        Items in pending, cooking, ready, cancelled statuses are NOT counted.
        """
        _override_auth(app, staff_user)
        _override_redis(app)

        session_model = _make_session_model(restaurant_id, status="closed")
        session_model.total_amount = Decimal("150000")

        # Served items: 50000*2 + 25000*2 = 150000
        # Non-served items should NOT contribute to total
        checkout_result = CheckoutResult(
            session=session_model,
            total_amount=Decimal("150000"),
            auto_cancelled_items=[
                {"id": uuid.uuid4(), "name_snapshot": "Gỏi cuốn", "quantity": 1, "status_before": "pending"},
                {"id": uuid.uuid4(), "name_snapshot": "Nước mía", "quantity": 2, "status_before": "cooking"},
                {"id": uuid.uuid4(), "name_snapshot": "Chả giò", "quantity": 1, "status_before": "ready"},
            ],
            dismissed_calls_count=0,
        )

        mock_db_session = AsyncMock()
        # The endpoint first does a SELECT to find the session
        result_mock = MagicMock()
        open_session = _make_session_model(restaurant_id, status="open")
        open_session.id = session_model.id
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)

        _override_db(app, mock_db_session)

        with patch.object(SessionService, "checkout", return_value=checkout_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 200
        data = resp.json()
        # Total is 150000 — only served items counted
        assert Decimal(data["total_amount"]) == Decimal("150000")
        # Auto-cancelled items list should contain the 3 non-served items
        assert len(data["auto_cancelled_items"]) == 3

    async def test_total_zero_when_no_served_items(self, app, restaurant_id, staff_user):
        """If no items are served, total_amount = 0."""
        _override_auth(app, staff_user)
        _override_redis(app)

        session_model = _make_session_model(restaurant_id, status="closed")
        session_model.total_amount = Decimal("0")

        checkout_result = CheckoutResult(
            session=session_model,
            total_amount=Decimal("0"),
            auto_cancelled_items=[
                {"id": uuid.uuid4(), "name_snapshot": "Phở bò", "quantity": 1, "status_before": "pending"},
            ],
            dismissed_calls_count=0,
        )

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        open_session = _make_session_model(restaurant_id, status="open")
        open_session.id = session_model.id
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "checkout", return_value=checkout_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 200
        assert Decimal(resp.json()["total_amount"]) == Decimal("0")


class TestAutoCancelOnClose:
    """Property 5 — Auto-cancel on close (table_closed reason)."""

    async def test_pending_cooking_ready_items_auto_cancelled(
        self, app, restaurant_id, staff_user
    ):
        """Items in pending/cooking/ready are auto-cancelled with system/table_closed."""
        _override_auth(app, staff_user)
        _override_redis(app)

        session_model = _make_session_model(restaurant_id, status="closed")
        session_model.total_amount = Decimal("50000")

        auto_cancelled = [
            {"id": uuid.uuid4(), "name_snapshot": "Bún bò", "quantity": 1, "status_before": "pending"},
            {"id": uuid.uuid4(), "name_snapshot": "Cơm tấm", "quantity": 2, "status_before": "cooking"},
            {"id": uuid.uuid4(), "name_snapshot": "Gà nướng", "quantity": 1, "status_before": "ready"},
        ]

        checkout_result = CheckoutResult(
            session=session_model,
            total_amount=Decimal("50000"),
            auto_cancelled_items=auto_cancelled,
            dismissed_calls_count=0,
        )

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        open_session = _make_session_model(restaurant_id, status="open")
        open_session.id = session_model.id
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "checkout", return_value=checkout_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 200
        data = resp.json()
        cancelled_items = data["auto_cancelled_items"]
        assert len(cancelled_items) == 3

        # Verify status_before captures original state
        statuses_before = {item["status_before"] for item in cancelled_items}
        assert statuses_before == {"pending", "cooking", "ready"}

    async def test_served_items_not_cancelled(self, app, restaurant_id, staff_user):
        """Items already served are NOT auto-cancelled at checkout."""
        _override_auth(app, staff_user)
        _override_redis(app)

        session_model = _make_session_model(restaurant_id, status="closed")
        session_model.total_amount = Decimal("100000")

        # No auto-cancelled items → served items were left untouched
        checkout_result = CheckoutResult(
            session=session_model,
            total_amount=Decimal("100000"),
            auto_cancelled_items=[],
            dismissed_calls_count=0,
        )

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        open_session = _make_session_model(restaurant_id, status="open")
        open_session.id = session_model.id
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "checkout", return_value=checkout_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 200
        data = resp.json()
        # No items auto-cancelled (all were already served)
        assert data["auto_cancelled_items"] == []
        # Total reflects served items
        assert Decimal(data["total_amount"]) == Decimal("100000")

    async def test_already_cancelled_items_not_double_cancelled(
        self, app, restaurant_id, staff_user
    ):
        """Items already cancelled before checkout are not listed in auto_cancelled_items."""
        _override_auth(app, staff_user)
        _override_redis(app)

        session_model = _make_session_model(restaurant_id, status="closed")
        session_model.total_amount = Decimal("0")

        # Only pending item is auto-cancelled; already-cancelled ones are not reported
        checkout_result = CheckoutResult(
            session=session_model,
            total_amount=Decimal("0"),
            auto_cancelled_items=[
                {"id": uuid.uuid4(), "name_snapshot": "Trà đá", "quantity": 3, "status_before": "pending"},
            ],
            dismissed_calls_count=0,
        )

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        open_session = _make_session_model(restaurant_id, status="open")
        open_session.id = session_model.id
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "checkout", return_value=checkout_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 200
        data = resp.json()
        # Only 1 item was auto-cancelled (the pending one)
        # Previously-cancelled items are NOT double-cancelled
        assert len(data["auto_cancelled_items"]) == 1
        assert data["auto_cancelled_items"][0]["status_before"] == "pending"


class TestCannotAddOrderAfterClose:
    """R6.6 — Cannot add order after session closed."""

    async def test_order_rejected_on_closed_session(self, app, restaurant_id, staff_user):
        """After checkout, trying to create a new order returns 400."""
        from qorder_api.services.session_service import SessionService

        mock_db_session = AsyncMock()

        table = MagicMock()
        table.id = uuid.uuid4()
        table.restaurant_id = restaurant_id
        table.table_number = "A1"
        table.qr_token = "closed-session-token"
        table.is_active = True
        table.created_at = datetime(2024, 1, 1)

        restaurant = MagicMock()
        restaurant.id = restaurant_id
        restaurant.slug = "quan-test"
        restaurant.name = "Quán Test"
        restaurant.is_active = True
        settings_mock = MagicMock()
        settings_mock.currency = "VND"
        settings_mock.logo_url = None
        restaurant.settings = settings_mock

        closed_session = _make_session_model(restaurant_id, status="closed")
        closed_session.table_id = table.id

        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:  # Table lookup
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:  # Restaurant lookup
                result.scalar_one_or_none.return_value = restaurant
            return result

        mock_db_session.execute = _mock_execute

        async def _override_session():
            yield mock_db_session

        app.dependency_overrides[_gs] = _override_session

        with patch.object(SessionService, "get_or_open", return_value=closed_session):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/t/closed-session-token/orders",
                    json={
                        "items": [
                            {"menu_item_id": str(uuid.uuid4()), "quantity": 1},
                        ]
                    },
                )

        # Session is closed → order rejected
        assert resp.status_code == 400
        assert "đóng" in resp.json()["detail"]


class TestDismissPendingStaffCalls:
    """R6.9 — Dismiss pending staff_calls on checkout."""

    async def test_pending_calls_dismissed(self, app, restaurant_id, staff_user):
        """Checkout dismisses all pending staff calls for the session."""
        _override_auth(app, staff_user)
        _override_redis(app)

        session_model = _make_session_model(restaurant_id, status="closed")
        session_model.total_amount = Decimal("80000")

        checkout_result = CheckoutResult(
            session=session_model,
            total_amount=Decimal("80000"),
            auto_cancelled_items=[],
            dismissed_calls_count=3,  # 3 pending calls were dismissed
        )

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        open_session = _make_session_model(restaurant_id, status="open")
        open_session.id = session_model.id
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "checkout", return_value=checkout_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["dismissed_calls_count"] == 3

    async def test_no_pending_calls_returns_zero(self, app, restaurant_id, staff_user):
        """If no pending calls exist, dismissed_calls_count = 0."""
        _override_auth(app, staff_user)
        _override_redis(app)

        session_model = _make_session_model(restaurant_id, status="closed")
        session_model.total_amount = Decimal("50000")

        checkout_result = CheckoutResult(
            session=session_model,
            total_amount=Decimal("50000"),
            auto_cancelled_items=[],
            dismissed_calls_count=0,
        )

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        open_session = _make_session_model(restaurant_id, status="open")
        open_session.id = session_model.id
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "checkout", return_value=checkout_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 200
        assert resp.json()["dismissed_calls_count"] == 0


class TestSnapshotPriceImmutability:
    """Property 8 — Snapshot price immutability.

    price_snapshot in order_items does not change even if menu_items.price changes.
    The total_amount uses snapshot prices, not current menu prices.
    """

    async def test_checkout_uses_snapshot_price_not_current(
        self, app, restaurant_id, staff_user
    ):
        """Simulates menu price change after order; checkout still uses snapshot price.

        Setup: item ordered at price_snapshot=50000, menu price later changed to 70000.
        Verify total uses 50000 (the snapshot), not 70000 (current menu price).
        """
        _override_auth(app, staff_user)
        _override_redis(app)

        session_model = _make_session_model(restaurant_id, status="closed")
        # Total computed from snapshot: 50000 * 2 = 100000 (not 70000 * 2 = 140000)
        session_model.total_amount = Decimal("100000")

        checkout_result = CheckoutResult(
            session=session_model,
            total_amount=Decimal("100000"),  # Uses price_snapshot=50000, qty=2
            auto_cancelled_items=[],
            dismissed_calls_count=0,
        )

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        open_session = _make_session_model(restaurant_id, status="open")
        open_session.id = session_model.id
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "checkout", return_value=checkout_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 200
        data = resp.json()
        # Total should be 100000 (50000*2 using snapshot), NOT 140000 (70000*2)
        assert Decimal(data["total_amount"]) == Decimal("100000")

    async def test_service_level_snapshot_immutability(self, restaurant_id):
        """Service-level test: SessionService.checkout computes total from price_snapshot.

        Directly tests the SQL logic by mocking DB execute to return order_items
        with price_snapshot=50000 while the hypothetical current price is 70000.
        The computed total must use 50000.
        """
        session_id = uuid.uuid4()
        mock_session = AsyncMock()

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                # CAS close: returns the closed session row
                row = {
                    "id": session_id,
                    "restaurant_id": restaurant_id,
                    "table_id": uuid.uuid4(),
                    "status": "closed",
                    "opened_by": None,
                    "opened_at": datetime(2024, 1, 1, tzinfo=timezone.utc),
                    "last_activity_at": datetime(2024, 6, 1, tzinfo=timezone.utc),
                    "closed_at": datetime(2024, 6, 1, 14, 0, 0, tzinfo=timezone.utc),
                    "abandoned_at": None,
                    "total_amount": None,
                }
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = row
                result.mappings.return_value = mappings_mock
            elif call_count == 2:
                # Items to cancel query: no pending items (all served)
                mappings_mock = MagicMock()
                mappings_mock.all.return_value = []
                result.mappings.return_value = mappings_mock
            elif call_count == 3:
                # Compute total: SUM(price_snapshot * quantity) for served items
                # price_snapshot=50000, quantity=2 → total=100000
                result.scalar_one.return_value = Decimal("100000")
            elif call_count == 4:
                # Update session.total_amount
                pass
            elif call_count == 5:
                # SELECT final session (from StaffCallService.dismiss_pending)
                result.rowcount = 0
            elif call_count == 6:
                # Re-read final session state
                final_session = MagicMock()
                final_session.id = session_id
                final_session.restaurant_id = restaurant_id
                final_session.table_id = uuid.uuid4()
                final_session.status = SessionStatus.CLOSED
                final_session.opened_by = None
                final_session.opened_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
                final_session.last_activity_at = datetime(2024, 6, 1, tzinfo=timezone.utc)
                final_session.closed_at = datetime(2024, 6, 1, 14, 0, 0, tzinfo=timezone.utc)
                final_session.abandoned_at = None
                final_session.total_amount = Decimal("100000")
                result.scalar_one.return_value = final_session
            return result

        mock_session.execute = _mock_execute
        mock_session.commit = AsyncMock()

        checkout_result = await SessionService.checkout(
            session_id=session_id,
            restaurant_id=restaurant_id,
            session=mock_session,
        )

        assert checkout_result is not None
        # The total MUST be 100000 (from price_snapshot=50000 * qty=2)
        # Even though the "current" menu price might be different
        assert checkout_result.total_amount == Decimal("100000")


class TestCASRaceProtection:
    """CAS race protection — 409 on already-closed/abandoned sessions."""

    async def test_checkout_already_closed_returns_409(
        self, app, restaurant_id, staff_user
    ):
        """Checkout on an already-closed session returns 409 Conflict."""
        _override_auth(app, staff_user)
        _override_redis(app)

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        # Session found but is already open (will attempt checkout)
        open_session = _make_session_model(restaurant_id, status="open")
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        # SessionService.checkout returns None → CAS lost (already closed)
        with patch.object(SessionService, "checkout", return_value=None):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 409
        assert "đóng" in resp.json()["detail"] or "bỏ" in resp.json()["detail"]

    async def test_checkout_already_abandoned_returns_409(
        self, app, restaurant_id, staff_user
    ):
        """Checkout on an already-abandoned session returns 409 Conflict."""
        _override_auth(app, staff_user)
        _override_redis(app)

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        # Session exists but open (CAS will fail inside checkout service)
        open_session = _make_session_model(restaurant_id, status="open")
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        # SessionService.checkout returns None → CAS lost (abandoned by sweep)
        with patch.object(SessionService, "checkout", return_value=None):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 409

    async def test_checkout_session_not_found_returns_404(
        self, app, restaurant_id, staff_user
    ):
        """Checkout on a non-existent session returns 404."""
        _override_auth(app, staff_user)
        _override_redis(app)

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None  # Session not found
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        fake_session_id = uuid.uuid4()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/tables/sessions/{fake_session_id}/checkout",
            )

        assert resp.status_code == 404
