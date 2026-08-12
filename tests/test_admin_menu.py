"""Tests for admin menu CRUD endpoints (R8.1, R3.2, R5.3).

Validates:
- Create/list/update menu categories with tenant isolation.
- Create/list/update menu items with prep_time_minutes required.
- Soft-hide via is_active, toggle is_available.
- Presets endpoint returns savory/light defaults from settings.
- Category validation: category_id must belong to same restaurant.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qorder_api.auth.jwt import create_access_token
from qorder_api.schemas.menu import (
    MenuCategoryCreate,
    MenuCategoryResponse,
    MenuCategoryUpdate,
    MenuItemCreate,
    MenuItemResponse,
    MenuItemUpdate,
    PrepTimePresetsResponse,
)


# ---------- Fixtures ----------


@pytest.fixture
def restaurant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def admin_user_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def admin_token(admin_user_id, restaurant_id) -> str:
    return create_access_token(
        user_id=admin_user_id,
        role="admin",
        restaurant_id=restaurant_id,
    )


@pytest.fixture
def app():
    from qorder_api.main import app as _app
    return _app


@pytest.fixture
def auth_headers(admin_token) -> dict[str, str]:
    return {"Authorization": f"Bearer {admin_token}"}


# ---------- Schema unit tests ----------


class TestMenuSchemas:
    """Validate Pydantic schema constraints."""

    def test_category_create_requires_name(self):
        with pytest.raises(Exception):
            MenuCategoryCreate(name="")  # min_length=1

    def test_category_create_defaults_sort_order(self):
        schema = MenuCategoryCreate(name="Drinks")
        assert schema.sort_order == 0

    def test_item_create_requires_prep_time(self):
        """prep_time_minutes is mandatory."""
        with pytest.raises(Exception):
            MenuItemCreate(name="Pho", price=Decimal("50000"))

    def test_item_create_valid(self):
        schema = MenuItemCreate(
            name="Pho",
            price=Decimal("50000"),
            prep_time_minutes=10,
        )
        assert schema.prep_time_minutes == 10
        assert schema.category_id is None

    def test_item_update_all_optional(self):
        schema = MenuItemUpdate()
        assert schema.name is None
        assert schema.is_available is None
        assert schema.is_active is None

    def test_presets_response(self):
        resp = PrepTimePresetsResponse(
            default_savory_minutes=10,
            default_light_minutes=5,
        )
        assert resp.default_savory_minutes == 10


# ---------- Helper to create mock category/item ----------


def _make_category(
    restaurant_id: uuid.UUID,
    name: str = "Appetizers",
    sort_order: int = 0,
    is_active: bool = True,
) -> MagicMock:
    cat = MagicMock()
    cat.id = uuid.uuid4()
    cat.restaurant_id = restaurant_id
    cat.name = name
    cat.sort_order = sort_order
    cat.is_active = is_active
    cat.created_at = datetime(2024, 1, 1)
    # Support attribute access for model_validate (from_attributes)
    cat.__class__.__name__ = "MenuCategory"
    return cat


def _make_item(
    restaurant_id: uuid.UUID,
    category_id: uuid.UUID | None = None,
    name: str = "Pho",
    price: Decimal = Decimal("50000"),
    prep_time_minutes: int = 10,
    is_available: bool = True,
    is_active: bool = True,
) -> MagicMock:
    item = MagicMock()
    item.id = uuid.uuid4()
    item.restaurant_id = restaurant_id
    item.category_id = category_id
    item.name = name
    item.description = None
    item.price = price
    item.prep_time_minutes = prep_time_minutes
    item.is_available = is_available
    item.is_active = is_active
    item.image_url = None
    item.sort_order = 0
    item.created_at = datetime(2024, 1, 1)
    item.updated_at = datetime(2024, 1, 1)
    return item


def _make_settings(restaurant_id: uuid.UUID) -> MagicMock:
    settings = MagicMock()
    settings.restaurant_id = restaurant_id
    settings.default_savory_minutes = 12
    settings.default_light_minutes = 4
    return settings


# ---------- Endpoint tests ----------


class TestMenuCategoryEndpoints:
    """Test /admin/menu-categories CRUD."""

    async def test_create_category_success(self, app, auth_headers, restaurant_id):
        """POST /admin/menu-categories returns 201 with new category."""
        from qorder_api.db import get_session as _gs

        created_cat = _make_category(restaurant_id, name="Main Course")

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock(return_value=None)

        # After refresh, the object is the "created" category
        # We patch the MenuCategory constructor to return our mock
        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with patch(
            "qorder_api.api.admin_menu_router.MenuCategory",
            return_value=created_cat,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/admin/menu-categories",
                    json={"name": "Main Course", "sort_order": 1},
                    headers=auth_headers,
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["name"] == "Main Course"
        assert data["is_active"] is True
        app.dependency_overrides.clear()

    async def test_create_category_no_auth_returns_401(self, app):
        """POST /admin/menu-categories without token returns 401."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/admin/menu-categories",
                json={"name": "Test"},
            )
        assert resp.status_code == 401

    async def test_list_categories(self, app, auth_headers, restaurant_id):
        """GET /admin/menu-categories returns categories for the restaurant."""
        from qorder_api.db import get_session as _gs

        cats = [
            _make_category(restaurant_id, "Cat A", 0),
            _make_category(restaurant_id, "Cat B", 1),
        ]

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_scalars = MagicMock()
        mock_scalars.all.return_value = cats
        mock_result.scalars.return_value = mock_scalars
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get(
                "/admin/menu-categories",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert len(data) == 2
        assert data[0]["name"] == "Cat A"
        app.dependency_overrides.clear()

    async def test_update_category_not_found(self, app, auth_headers, restaurant_id):
        """PATCH /admin/menu-categories/{id} returns 404 for unknown category."""
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
            resp = await ac.patch(
                f"/admin/menu-categories/{uuid.uuid4()}",
                json={"name": "Updated"},
                headers=auth_headers,
            )

        assert resp.status_code == 404
        app.dependency_overrides.clear()

    async def test_update_category_soft_hide(self, app, auth_headers, restaurant_id):
        """PATCH with is_active=false soft-hides the category."""
        from qorder_api.db import get_session as _gs

        category = _make_category(restaurant_id, "Drinks")

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = category
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.patch(
                f"/admin/menu-categories/{category.id}",
                json={"is_active": False},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        # Verify is_active was set on the model
        assert category.is_active is False
        app.dependency_overrides.clear()


class TestMenuItemEndpoints:
    """Test /admin/menu-items CRUD."""

    async def test_create_item_success(self, app, auth_headers, restaurant_id):
        """POST /admin/menu-items returns 201."""
        from qorder_api.db import get_session as _gs

        created_item = _make_item(restaurant_id)

        mock_session = AsyncMock()
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        with patch(
            "qorder_api.api.admin_menu_router.MenuItem",
            return_value=created_item,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    "/admin/menu-items",
                    json={
                        "name": "Pho",
                        "price": "50000",
                        "prep_time_minutes": 10,
                    },
                    headers=auth_headers,
                )

        assert resp.status_code == 201
        data = resp.json()
        assert data["prep_time_minutes"] == 10
        app.dependency_overrides.clear()

    async def test_create_item_missing_prep_time_returns_422(self, app, auth_headers):
        """POST /admin/menu-items without prep_time_minutes → 422."""
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.post(
                "/admin/menu-items",
                json={"name": "Pho", "price": "50000"},
                headers=auth_headers,
            )

        assert resp.status_code == 422

    async def test_create_item_invalid_category(self, app, auth_headers, restaurant_id):
        """POST with category_id from another restaurant → 400."""
        from qorder_api.db import get_session as _gs

        mock_session = AsyncMock()
        # First execute: category check returns None (not found)
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
            resp = await ac.post(
                "/admin/menu-items",
                json={
                    "name": "Pho",
                    "price": "50000",
                    "prep_time_minutes": 10,
                    "category_id": str(uuid.uuid4()),
                },
                headers=auth_headers,
            )

        assert resp.status_code == 400
        assert "Category not found" in resp.json()["detail"]
        app.dependency_overrides.clear()

    async def test_update_item_toggle_available(self, app, auth_headers, restaurant_id):
        """PATCH with is_available=false marks item out of stock."""
        from qorder_api.db import get_session as _gs

        item = _make_item(restaurant_id)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = item
        mock_session.execute = AsyncMock(return_value=mock_result)
        mock_session.add = MagicMock()
        mock_session.commit = AsyncMock()
        mock_session.refresh = AsyncMock()

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.patch(
                f"/admin/menu-items/{item.id}",
                json={"is_available": False},
                headers=auth_headers,
            )

        assert resp.status_code == 200
        assert item.is_available is False
        app.dependency_overrides.clear()

    async def test_update_item_not_found(self, app, auth_headers):
        """PATCH /admin/menu-items/{id} returns 404 for unknown item."""
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
            resp = await ac.patch(
                f"/admin/menu-items/{uuid.uuid4()}",
                json={"name": "New Name"},
                headers=auth_headers,
            )

        assert resp.status_code == 404
        app.dependency_overrides.clear()


class TestPresetsEndpoint:
    """Test GET /admin/settings/presets."""

    async def test_presets_returns_settings(self, app, auth_headers, restaurant_id):
        """Returns savory/light presets from restaurant_settings."""
        from qorder_api.db import get_session as _gs

        settings = _make_settings(restaurant_id)

        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = settings
        mock_session.execute = AsyncMock(return_value=mock_result)

        async def _override_session():
            yield mock_session

        app.dependency_overrides[_gs] = _override_session

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://test",
        ) as ac:
            resp = await ac.get(
                "/admin/settings/presets",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["default_savory_minutes"] == 12
        assert data["default_light_minutes"] == 4
        app.dependency_overrides.clear()

    async def test_presets_no_settings_returns_defaults(
        self, app, auth_headers, restaurant_id
    ):
        """If no settings row exists, return sensible defaults."""
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
            resp = await ac.get(
                "/admin/settings/presets",
                headers=auth_headers,
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["default_savory_minutes"] == 10
        assert data["default_light_minutes"] == 5
        app.dependency_overrides.clear()
