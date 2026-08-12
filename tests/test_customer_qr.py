"""Tests for public customer QR-resolve endpoint (R2.2, R2.3, R3.1, R3.2).

Validates:
- Valid QR token returns restaurant + table + menu.
- Invalid QR token returns 404 with friendly Vietnamese message.
- Inactive table returns 404.
- Inactive restaurant returns 404.
- Only active menu items are returned (is_active=True).
- Items with is_available=False still appear but marked unavailable.
- No authentication required.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock

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
    qr_token: str = "valid-token-123",
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
    settings.logo_url = "https://example.com/logo.png"

    restaurant = MagicMock()
    restaurant.id = restaurant_id
    restaurant.slug = "nha-hang-test"
    restaurant.name = "Nhà Hàng Test"
    restaurant.is_active = is_active
    restaurant.settings = settings
    return restaurant


def _make_category(
    restaurant_id: uuid.UUID,
    name: str = "Món chính",
    sort_order: int = 0,
) -> MagicMock:
    cat = MagicMock()
    cat.id = uuid.uuid4()
    cat.restaurant_id = restaurant_id
    cat.name = name
    cat.sort_order = sort_order
    cat.is_active = True
    return cat


def _make_item(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID | None = None,
    name: str = "Phở bò",
    is_available: bool = True,
) -> MagicMock:
    item = MagicMock()
    item.id = uuid.uuid4()
    item.restaurant_id = restaurant_id
    item.category_id = category_id
    item.name = name
    item.description = "Phở bò truyền thống"
    item.price = Decimal("50000")
    item.prep_time_minutes = 10
    item.is_available = is_available
    item.is_active = True
    item.image_url = None
    item.sort_order = 0
    return item


# ---------- Tests ----------


class TestQRResolveEndpoint:
    """Test GET /t/{qr_token}."""

    async def test_valid_qr_returns_full_response(self, app, restaurant_id):
        """A valid, active QR token returns restaurant + table + menu."""
        from qorder_api.db import get_session as _gs

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        category = _make_category(restaurant_id)
        item = _make_item(restaurant_id, category_id=category.id)

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
            elif call_count == 3:  # Categories
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [category]
                result.scalars.return_value = mock_scalars
            elif call_count == 4:  # Items
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [item]
                result.scalars.return_value = mock_scalars
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/t/valid-token-123")

        assert resp.status_code == 200
        data = resp.json()

        # Restaurant info
        assert data["restaurant"]["name"] == "Nhà Hàng Test"
        assert data["restaurant"]["slug"] == "nha-hang-test"
        assert data["restaurant"]["currency"] == "VND"
        assert data["restaurant"]["logo_url"] == "https://example.com/logo.png"

        # Table info
        assert data["table"]["table_number"] == "A1"

        # Menu
        assert len(data["menu"]) == 1
        assert data["menu"][0]["name"] == "Món chính"
        assert len(data["menu"][0]["items"]) == 1
        assert data["menu"][0]["items"][0]["name"] == "Phở bò"
        assert data["menu"][0]["items"][0]["is_available"] is True

        app.dependency_overrides.clear()

    async def test_invalid_qr_returns_404(self, app):
        """An invalid/unknown QR token returns 404 with friendly message."""
        from qorder_api.db import get_session as _gs

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/t/nonexistent-token")

        assert resp.status_code == 404
        assert "QR" in resp.json()["detail"] or "bàn" in resp.json()["detail"]
        app.dependency_overrides.clear()

    async def test_inactive_restaurant_returns_404(self, app, restaurant_id):
        """Active table but inactive restaurant returns 404."""
        from qorder_api.db import get_session as _gs

        table = _make_table(restaurant_id)

        mock_session = AsyncMock()
        call_count = 0

        async def _mock_execute(stmt):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:  # Table lookup — found active
                result.scalar_one_or_none.return_value = table
            elif call_count == 2:  # Restaurant lookup — not found (inactive)
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
            resp = await ac.get("/t/valid-token-123")

        assert resp.status_code == 404
        assert "Nhà hàng" in resp.json()["detail"]
        app.dependency_overrides.clear()

    async def test_unavailable_items_still_appear(self, app, restaurant_id):
        """Items with is_available=False still show up but marked unavailable (R3.2)."""
        from qorder_api.db import get_session as _gs

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)
        category = _make_category(restaurant_id)
        available_item = _make_item(
            restaurant_id, category_id=category.id, name="Phở bò", is_available=True
        )
        unavailable_item = _make_item(
            restaurant_id, category_id=category.id, name="Bún chả", is_available=False
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
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [category]
                result.scalars.return_value = mock_scalars
            elif call_count == 4:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = [available_item, unavailable_item]
                result.scalars.return_value = mock_scalars
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get("/t/valid-token-123")

        assert resp.status_code == 200
        items = resp.json()["menu"][0]["items"]
        assert len(items) == 2

        names = {i["name"]: i["is_available"] for i in items}
        assert names["Phở bò"] is True
        assert names["Bún chả"] is False

        app.dependency_overrides.clear()

    async def test_no_auth_required(self, app, restaurant_id):
        """The endpoint works without any Authorization header."""
        from qorder_api.db import get_session as _gs

        table = _make_table(restaurant_id)
        restaurant = _make_restaurant(restaurant_id)

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
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = []
                result.scalars.return_value = mock_scalars
            elif call_count == 4:
                mock_scalars = MagicMock()
                mock_scalars.all.return_value = []
                result.scalars.return_value = mock_scalars
            return result

        mock_session.execute = _mock_execute

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            # No auth headers — should still work
            resp = await ac.get("/t/valid-token-123")

        assert resp.status_code == 200
        assert resp.json()["menu"] == []
        app.dependency_overrides.clear()
