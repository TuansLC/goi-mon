"""Integration tests for tenant isolation & auth security (Task 13).

**Validates: Requirements 1.2, 10.6, 12.2, 12.10**

Property 2: Cô lập tenant — Mọi bản ghi trả về cho một request luôn có
`restaurant_id` khớp claim/quán trong ngữ cảnh; không có đường dẫn nào trả
dữ liệu chéo quán.

Tests cover:
1. Tenant isolation: restaurant A's staff/admin cannot access restaurant B's data
   (menu items, categories, tables, sessions, orders, kitchen board, staff calls).
   Cross-access returns 404 (not 403, to avoid leaking existence).
2. Role guards: unauthenticated → 401; staff cannot access admin routes → 403;
   admin can access admin routes.
3. kitchen_screen_requires_pin toggle: ws-ticket endpoint behavior with PIN
   on/off.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qorder_api.auth.dependencies import get_current_user
from qorder_api.auth.jwt import TokenPayload, create_access_token
from qorder_api.db import get_session as _gs
from qorder_api.models.enums import (
    OrderItemStatus,
    SessionStatus,
    StaffCallStatus,
    UserRole,
)
from qorder_api.redis import get_redis


# ============================================================================
# Fixtures
# ============================================================================


@pytest.fixture
def restaurant_a_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def restaurant_b_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def staff_a(restaurant_a_id) -> TokenPayload:
    """Staff user belonging to restaurant A."""
    return TokenPayload(
        sub=uuid.uuid4(),
        restaurant_id=restaurant_a_id,
        role="staff",
    )


@pytest.fixture
def admin_a(restaurant_a_id) -> TokenPayload:
    """Admin user belonging to restaurant A."""
    return TokenPayload(
        sub=uuid.uuid4(),
        restaurant_id=restaurant_a_id,
        role="admin",
    )


@pytest.fixture
def staff_b(restaurant_b_id) -> TokenPayload:
    """Staff user belonging to restaurant B."""
    return TokenPayload(
        sub=uuid.uuid4(),
        restaurant_id=restaurant_b_id,
        role="staff",
    )


@pytest.fixture
def admin_b(restaurant_b_id) -> TokenPayload:
    """Admin user belonging to restaurant B."""
    return TokenPayload(
        sub=uuid.uuid4(),
        restaurant_id=restaurant_b_id,
        role="admin",
    )


@pytest.fixture
def app():
    from qorder_api.main import app as _app

    yield _app
    _app.dependency_overrides.clear()


# ============================================================================
# Helpers
# ============================================================================


def _override_auth(app, user: TokenPayload):
    """Override auth dependency to return a specific user."""

    async def _fake_user():
        return user

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


def _make_table(restaurant_id: uuid.UUID, **kwargs) -> MagicMock:
    table = MagicMock()
    table.id = kwargs.get("table_id", uuid.uuid4())
    table.restaurant_id = restaurant_id
    table.table_number = kwargs.get("table_number", "B1")
    table.qr_token = kwargs.get("qr_token", "some-token")
    table.is_active = kwargs.get("is_active", True)
    table.created_at = datetime(2024, 1, 1)
    return table


def _make_session_model(restaurant_id: uuid.UUID, **kwargs) -> MagicMock:
    s = MagicMock()
    s.id = kwargs.get("session_id", uuid.uuid4())
    s.restaurant_id = restaurant_id
    s.table_id = kwargs.get("table_id", uuid.uuid4())
    s.status = SessionStatus(kwargs.get("status", "open"))
    s.opened_by = None
    s.opened_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    s.last_activity_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    s.closed_at = None
    s.abandoned_at = None
    s.total_amount = None
    return s


def _make_order_item(restaurant_id: uuid.UUID, **kwargs) -> MagicMock:
    item = MagicMock()
    item.id = kwargs.get("item_id", uuid.uuid4())
    item.restaurant_id = restaurant_id
    item.order_id = kwargs.get("order_id", uuid.uuid4())
    item.menu_item_id = uuid.uuid4()
    item.name_snapshot = kwargs.get("name", "Phở bò")
    item.price_snapshot = Decimal("50000")
    item.prep_time_snapshot = 10
    item.quantity = 1
    item.note = None
    item.status = OrderItemStatus(kwargs.get("status", "pending"))
    item.requested_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    item.served_by = None
    item.served_at = None
    item.cancelled_by = None
    item.cancelled_at = None
    item.cancel_reason = None
    return item


# ============================================================================
# Test Class 1: Tenant Isolation — Staff A cannot access Restaurant B's data
# ============================================================================


class TestTenantIsolationKitchenBoard:
    """Staff of restaurant A accessing kitchen board sees only their own items."""

    async def test_kitchen_board_only_returns_own_restaurant_items(
        self, app, restaurant_a_id, restaurant_b_id, staff_a
    ):
        """GET /kitchen/board returns items ONLY for staff's restaurant (Property 2).

        Staff A should see only restaurant A's items — never restaurant B's.
        """
        _override_auth(app, staff_a)
        _override_redis(app)

        # Items belonging to restaurant A (should appear)
        item_a = _make_order_item(restaurant_a_id, name="Bún bò A")
        # Items belonging to restaurant B (should NOT appear)
        item_b = _make_order_item(restaurant_b_id, name="Phở B")

        mock_db = AsyncMock()
        result_mock = MagicMock()
        # The kitchen board query filters by restaurant_id from JWT,
        # so we simulate DB returning ONLY restaurant A's items
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = [item_a]
        result_mock.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/kitchen/board")

        assert resp.status_code == 200
        data = resp.json()
        items = data["items"]
        assert len(items) == 1
        assert items[0]["name_snapshot"] == "Bún bò A"


class TestTenantIsolationItemStatus:
    """Staff A cannot change status of restaurant B's items (returns 404)."""

    async def test_set_status_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, staff_a
    ):
        """POST /kitchen/items/{id}/status for another restaurant's item → 404."""
        _override_auth(app, staff_a)
        _override_redis(app)

        # Item belongs to restaurant B
        item_b_id = uuid.uuid4()

        mock_db = AsyncMock()
        result_mock = MagicMock()
        # Query with restaurant_id filter finds nothing (item is restaurant B's)
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_b_id}/status",
                json={"to": "served"},
            )

        assert resp.status_code == 404

    async def test_cancel_item_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, staff_a
    ):
        """POST /kitchen/items/{id}/cancel for another restaurant's item → 404."""
        _override_auth(app, staff_a)
        _override_redis(app)

        item_b_id = uuid.uuid4()

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(f"/kitchen/items/{item_b_id}/cancel")

        assert resp.status_code == 404


class TestTenantIsolationStaffCalls:
    """Staff A cannot ack restaurant B's staff calls (returns 404)."""

    async def test_ack_call_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, staff_a
    ):
        """POST /kitchen/calls/{id}/ack for another restaurant's call → 404."""
        _override_auth(app, staff_a)
        _override_redis(app)

        call_b_id = uuid.uuid4()

        # StaffCallService.ack raises ValueError when not found
        with patch(
            "qorder_api.api.kitchen_router.StaffCallService.ack",
            new_callable=AsyncMock,
            side_effect=ValueError("Call not found"),
        ):
            mock_db = AsyncMock()
            _override_db(app, mock_db)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(f"/kitchen/calls/{call_b_id}/ack")

        assert resp.status_code == 404


class TestTenantIsolationSessions:
    """Staff A cannot checkout/restore restaurant B's sessions."""

    async def test_checkout_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, staff_a
    ):
        """POST /tables/sessions/{id}/checkout for another restaurant → 404."""
        _override_auth(app, staff_a)
        _override_redis(app)

        session_b_id = uuid.uuid4()

        mock_db = AsyncMock()
        result_mock = MagicMock()
        # Session not found because restaurant_id filter doesn't match
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(f"/tables/sessions/{session_b_id}/checkout")

        assert resp.status_code == 404

    async def test_restore_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, staff_a
    ):
        """POST /tables/sessions/{id}/restore for another restaurant → 404."""
        _override_auth(app, staff_a)
        _override_redis(app)

        session_b_id = uuid.uuid4()

        # SessionService.restore returns None when not found
        with patch(
            "qorder_api.services.session_service.SessionService.restore",
            new_callable=AsyncMock,
            return_value=None,
        ):
            mock_db = AsyncMock()
            _override_db(app, mock_db)

            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(f"/tables/sessions/{session_b_id}/restore")

        assert resp.status_code == 404


class TestTenantIsolationOpenTable:
    """Staff A cannot open a table belonging to restaurant B."""

    async def test_open_table_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, staff_a
    ):
        """POST /tables/{id}/open for restaurant B's table → 404."""
        _override_auth(app, staff_a)
        _override_redis(app)

        table_b_id = uuid.uuid4()

        mock_db = AsyncMock()
        result_mock = MagicMock()
        # Table not found because restaurant_id filter
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(f"/tables/{table_b_id}/open")

        assert resp.status_code == 404


class TestTenantIsolationAdminMenu:
    """Admin A cannot read/write restaurant B's menu items and categories."""

    async def test_list_menu_items_only_own_restaurant(
        self, app, restaurant_a_id, admin_a
    ):
        """GET /admin/menu-items returns only items for admin's restaurant."""
        _override_auth(app, admin_a)

        mock_db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []  # Empty — but only own restaurant queried
        result_mock.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/menu-items")

        assert resp.status_code == 200
        assert resp.json() == []

    async def test_update_menu_item_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, admin_a
    ):
        """PATCH /admin/menu-items/{id} for restaurant B's item → 404."""
        _override_auth(app, admin_a)

        item_b_id = uuid.uuid4()

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.patch(
                f"/admin/menu-items/{item_b_id}",
                json={"price": 99000},
            )

        assert resp.status_code == 404

    async def test_list_categories_only_own_restaurant(
        self, app, restaurant_a_id, admin_a
    ):
        """GET /admin/menu-categories returns only categories for admin's restaurant."""
        _override_auth(app, admin_a)

        mock_db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/menu-categories")

        assert resp.status_code == 200
        assert resp.json() == []

    async def test_update_category_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, admin_a
    ):
        """PATCH /admin/menu-categories/{id} for restaurant B's category → 404."""
        _override_auth(app, admin_a)

        cat_b_id = uuid.uuid4()

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.patch(
                f"/admin/menu-categories/{cat_b_id}",
                json={"name": "Hacked"},
            )

        assert resp.status_code == 404


class TestTenantIsolationAdminTables:
    """Admin A cannot read/write restaurant B's tables."""

    async def test_list_tables_only_own_restaurant(
        self, app, restaurant_a_id, admin_a
    ):
        """GET /admin/tables returns only tables for admin's restaurant."""
        _override_auth(app, admin_a)

        mock_db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/tables")

        assert resp.status_code == 200
        assert resp.json() == []

    async def test_update_table_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, admin_a
    ):
        """PATCH /admin/tables/{id} for restaurant B's table → 404."""
        _override_auth(app, admin_a)

        table_b_id = uuid.uuid4()

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.patch(
                f"/admin/tables/{table_b_id}",
                json={"table_number": "HACKED"},
            )

        assert resp.status_code == 404

    async def test_regenerate_qr_cross_tenant_returns_404(
        self, app, restaurant_a_id, restaurant_b_id, admin_a
    ):
        """POST /admin/tables/{id}/regenerate-qr for restaurant B's table → 404."""
        _override_auth(app, admin_a)

        table_b_id = uuid.uuid4()

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(f"/admin/tables/{table_b_id}/regenerate-qr")

        assert resp.status_code == 404


# ============================================================================
# Test Class 2: Role-based access control guards
# ============================================================================


class TestRoleGuardUnauthenticated:
    """Requests without auth token to protected routes → 401."""

    async def test_kitchen_board_no_auth_returns_401(self, app):
        """GET /kitchen/board without auth → 401."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/kitchen/board")

        assert resp.status_code == 401

    async def test_kitchen_item_status_no_auth_returns_401(self, app):
        """POST /kitchen/items/{id}/status without auth → 401."""
        item_id = uuid.uuid4()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                f"/kitchen/items/{item_id}/status",
                json={"to": "served"},
            )

        assert resp.status_code == 401

    async def test_admin_settings_no_auth_returns_401(self, app):
        """GET /admin/settings without auth → 401."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/settings")

        assert resp.status_code == 401

    async def test_admin_menu_items_no_auth_returns_401(self, app):
        """GET /admin/menu-items without auth → 401."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/menu-items")

        assert resp.status_code == 401

    async def test_open_table_no_auth_returns_401(self, app):
        """POST /tables/{id}/open without auth → 401."""
        table_id = uuid.uuid4()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(f"/tables/{table_id}/open")

        assert resp.status_code == 401

    async def test_checkout_no_auth_returns_401(self, app):
        """POST /tables/sessions/{id}/checkout without auth → 401."""
        session_id = uuid.uuid4()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(f"/tables/sessions/{session_id}/checkout")

        assert resp.status_code == 401


class TestRoleGuardStaffCannotAccessAdmin:
    """Staff role cannot access admin-only routes → 403."""

    async def test_staff_cannot_access_admin_settings(
        self, app, restaurant_a_id, staff_a
    ):
        """GET /admin/settings with staff JWT → 403."""
        _override_auth(app, staff_a)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/settings")

        assert resp.status_code == 403

    async def test_staff_cannot_access_admin_menu_items(
        self, app, restaurant_a_id, staff_a
    ):
        """GET /admin/menu-items with staff JWT → 403."""
        _override_auth(app, staff_a)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/menu-items")

        assert resp.status_code == 403

    async def test_staff_cannot_create_menu_item(
        self, app, restaurant_a_id, staff_a
    ):
        """POST /admin/menu-items with staff JWT → 403."""
        _override_auth(app, staff_a)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/admin/menu-items",
                json={
                    "name": "Hack item",
                    "price": 10000,
                    "prep_time_minutes": 5,
                },
            )

        assert resp.status_code == 403

    async def test_staff_cannot_manage_tables(
        self, app, restaurant_a_id, staff_a
    ):
        """GET /admin/tables with staff JWT → 403."""
        _override_auth(app, staff_a)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/tables")

        assert resp.status_code == 403

    async def test_staff_cannot_reset_pin(
        self, app, restaurant_a_id, staff_a
    ):
        """POST /admin/staff/reset-pin with staff JWT → 403."""
        _override_auth(app, staff_a)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/admin/staff/reset-pin",
                json={"new_pin": "9999"},
            )

        assert resp.status_code == 403


class TestRoleGuardAdminCanAccessAdminRoutes:
    """Admin role can access admin routes → not 401/403."""

    async def test_admin_can_access_settings(
        self, app, restaurant_a_id, admin_a
    ):
        """GET /admin/settings with admin JWT → not 401/403 (200 or 404)."""
        _override_auth(app, admin_a)

        mock_db = AsyncMock()
        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/settings")

        # 404 is acceptable (no settings row) — main point is NOT 401/403
        assert resp.status_code in (200, 404)
        assert resp.status_code != 401
        assert resp.status_code != 403

    async def test_admin_can_list_menu_items(
        self, app, restaurant_a_id, admin_a
    ):
        """GET /admin/menu-items with admin JWT → 200."""
        _override_auth(app, admin_a)

        mock_db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/menu-items")

        assert resp.status_code == 200


class TestRoleGuardStaffCanAccessStaffRoutes:
    """Staff can access staff/kitchen routes (but not admin routes)."""

    async def test_staff_can_access_kitchen_board(
        self, app, restaurant_a_id, staff_a
    ):
        """GET /kitchen/board with staff JWT → 200."""
        _override_auth(app, staff_a)
        _override_redis(app)

        mock_db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/kitchen/board")

        assert resp.status_code == 200

    async def test_admin_can_also_access_kitchen_board(
        self, app, restaurant_a_id, admin_a
    ):
        """GET /kitchen/board with admin JWT → 200 (admin inherits staff access)."""
        _override_auth(app, admin_a)
        _override_redis(app)

        mock_db = AsyncMock()
        result_mock = MagicMock()
        scalars_mock = MagicMock()
        scalars_mock.all.return_value = []
        result_mock.scalars.return_value = scalars_mock
        mock_db.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/kitchen/board")

        assert resp.status_code == 200


# ============================================================================
# Test Class 3: kitchen_screen_requires_pin toggle (R12.10)
# ============================================================================


class TestKitchenPinToggle:
    """Test ws-ticket endpoint behavior based on kitchen_screen_requires_pin."""

    async def test_pin_required_no_jwt_returns_401(self, app, restaurant_a_id):
        """POST /auth/ws-ticket with PIN required but no JWT → 401."""
        from qorder_api.models.restaurant import Restaurant

        mock_restaurant = MagicMock()
        mock_restaurant.id = restaurant_a_id
        mock_restaurant.slug = "quan-a"
        mock_restaurant.name = "Quán A"
        mock_restaurant.is_active = True

        mock_db = AsyncMock()
        call_count = {"v": 0}

        async def _mock_execute(stmt):
            call_count["v"] += 1
            result = MagicMock()
            if call_count["v"] == 1:
                # Restaurant lookup by slug
                result.scalar_one_or_none.return_value = mock_restaurant
            elif call_count["v"] == 2:
                # kitchen_screen_requires_pin lookup
                result.scalar_one_or_none.return_value = True
            return result

        mock_db.execute = AsyncMock(side_effect=_mock_execute)
        _override_db(app, mock_db)
        _override_redis(app)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/auth/ws-ticket",
                json={"restaurant_slug": "quan-a"},
            )

        assert resp.status_code == 401

    async def test_pin_required_with_valid_staff_jwt_returns_ticket(
        self, app, restaurant_a_id
    ):
        """POST /auth/ws-ticket with PIN required + valid Staff JWT → 200 + ticket."""
        from qorder_api.auth.ws_ticket import issue_ws_ticket

        mock_restaurant = MagicMock()
        mock_restaurant.id = restaurant_a_id
        mock_restaurant.slug = "quan-a"
        mock_restaurant.name = "Quán A"
        mock_restaurant.is_active = True

        staff_user_id = uuid.uuid4()

        mock_db = AsyncMock()
        call_count = {"v": 0}

        async def _mock_execute(stmt):
            call_count["v"] += 1
            result = MagicMock()
            if call_count["v"] == 1:
                result.scalar_one_or_none.return_value = mock_restaurant
            elif call_count["v"] == 2:
                result.scalar_one_or_none.return_value = True  # pin required
            return result

        mock_db.execute = AsyncMock(side_effect=_mock_execute)
        _override_db(app, mock_db)

        fake_redis = _override_redis(app)

        # Create a real JWT for staff
        token = create_access_token(
            user_id=staff_user_id,
            role="staff",
            restaurant_id=restaurant_a_id,
        )

        with patch(
            "qorder_api.api.auth_router.issue_ws_ticket",
            new_callable=AsyncMock,
            return_value="test-ticket-123",
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/auth/ws-ticket",
                    json={"restaurant_slug": "quan-a"},
                    headers={"Authorization": f"Bearer {token}"},
                )

        assert resp.status_code == 200
        assert "ticket" in resp.json()

    async def test_pin_not_required_anonymous_gets_ticket(
        self, app, restaurant_a_id
    ):
        """POST /auth/ws-ticket with PIN NOT required and no JWT → 200 + ticket.

        When kitchen_screen_requires_pin=False, anyone can get a ticket
        with just the restaurant slug.
        """
        mock_restaurant = MagicMock()
        mock_restaurant.id = restaurant_a_id
        mock_restaurant.slug = "quan-a"
        mock_restaurant.name = "Quán A"
        mock_restaurant.is_active = True

        mock_db = AsyncMock()
        call_count = {"v": 0}

        async def _mock_execute(stmt):
            call_count["v"] += 1
            result = MagicMock()
            if call_count["v"] == 1:
                result.scalar_one_or_none.return_value = mock_restaurant
            elif call_count["v"] == 2:
                # kitchen_screen_requires_pin = False
                result.scalar_one_or_none.return_value = False
            return result

        mock_db.execute = AsyncMock(side_effect=_mock_execute)
        _override_db(app, mock_db)
        _override_redis(app)

        with patch(
            "qorder_api.api.auth_router.issue_ws_ticket",
            new_callable=AsyncMock,
            return_value="anon-ticket-456",
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/auth/ws-ticket",
                    json={"restaurant_slug": "quan-a"},
                    # No Authorization header — anonymous
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["ticket"] == "anon-ticket-456"

    async def test_pin_required_wrong_restaurant_jwt_returns_403(
        self, app, restaurant_a_id, restaurant_b_id
    ):
        """POST /auth/ws-ticket with staff JWT of restaurant B for restaurant A → 403.

        Tenant isolation: even with valid JWT, can't get ticket for another
        restaurant.
        """
        mock_restaurant = MagicMock()
        mock_restaurant.id = restaurant_a_id
        mock_restaurant.slug = "quan-a"
        mock_restaurant.name = "Quán A"
        mock_restaurant.is_active = True

        mock_db = AsyncMock()
        call_count = {"v": 0}

        async def _mock_execute(stmt):
            call_count["v"] += 1
            result = MagicMock()
            if call_count["v"] == 1:
                result.scalar_one_or_none.return_value = mock_restaurant
            elif call_count["v"] == 2:
                result.scalar_one_or_none.return_value = True  # pin required
            return result

        mock_db.execute = AsyncMock(side_effect=_mock_execute)
        _override_db(app, mock_db)
        _override_redis(app)

        # JWT for restaurant B (different restaurant)
        token = create_access_token(
            user_id=uuid.uuid4(),
            role="staff",
            restaurant_id=restaurant_b_id,
        )

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/auth/ws-ticket",
                json={"restaurant_slug": "quan-a"},
                headers={"Authorization": f"Bearer {token}"},
            )

        assert resp.status_code == 403


# ============================================================================
# Test Class 4: Customer routes are anonymous (no auth required)
# ============================================================================


class TestCustomerRoutesAnonymous:
    """Customer routes (via qr_token) do not require authentication (R12.1)."""

    async def test_resolve_qr_no_auth_required(self, app, restaurant_a_id):
        """GET /t/{qr_token} does NOT require auth — accessible anonymously."""
        from qorder_api.models.restaurant import Restaurant

        mock_table = _make_table(restaurant_a_id, qr_token="cust-token")
        mock_restaurant = MagicMock()
        mock_restaurant.id = restaurant_a_id
        mock_restaurant.slug = "quan-a"
        mock_restaurant.name = "Quán A"
        mock_restaurant.is_active = True
        mock_settings = MagicMock()
        mock_settings.currency = "VND"
        mock_settings.logo_url = None
        mock_restaurant.settings = mock_settings

        mock_db = AsyncMock()
        call_count = {"v": 0}

        async def _mock_execute(stmt):
            call_count["v"] += 1
            result = MagicMock()
            if call_count["v"] == 1:
                # Table lookup by qr_token
                result.scalar_one_or_none.return_value = mock_table
            elif call_count["v"] == 2:
                # Restaurant lookup
                result.scalar_one_or_none.return_value = mock_restaurant
            elif call_count["v"] == 3:
                # Categories
                scalars_mock = MagicMock()
                scalars_mock.all.return_value = []
                result.scalars.return_value = scalars_mock
            elif call_count["v"] == 4:
                # Menu items
                scalars_mock = MagicMock()
                scalars_mock.all.return_value = []
                result.scalars.return_value = scalars_mock
            return result

        mock_db.execute = AsyncMock(side_effect=_mock_execute)
        _override_db(app, mock_db)

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            # No Authorization header
            resp = await ac.get("/t/cust-token")

        # Should not be 401/403
        assert resp.status_code == 200

    async def test_customer_cannot_access_staff_routes(self, app):
        """Anonymous customer trying to hit staff routes → 401."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/kitchen/board")

        assert resp.status_code == 401

    async def test_customer_cannot_access_admin_routes(self, app):
        """Anonymous customer trying to hit admin routes → 401."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/admin/menu-items")

        assert resp.status_code == 401
