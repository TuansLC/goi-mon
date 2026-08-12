"""Admin CRUD endpoints for menu categories and menu items (R8.1, R3.2, R5.3).

All routes inherit the ``/admin`` prefix and ``require_role("admin")`` guard
from the parent admin router. Queries filter by ``restaurant_id`` from the JWT
to enforce tenant isolation.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.auth.dependencies import CurrentUser, require_role
from qorder_api.db import get_session
from qorder_api.models.menu import MenuCategory, MenuItem
from qorder_api.models.restaurant import RestaurantSettings
from qorder_api.schemas.menu import (
    MenuCategoryCreate,
    MenuCategoryResponse,
    MenuCategoryUpdate,
    MenuItemCreate,
    MenuItemResponse,
    MenuItemUpdate,
    PrepTimePresetsResponse,
)

router = APIRouter(
    prefix="/admin",
    tags=["admin-menu"],
    dependencies=[Depends(require_role("admin"))],
)


# ─── Menu Categories ─────────────────────────────────────────────────────────


@router.post(
    "/menu-categories",
    response_model=MenuCategoryResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_menu_category(
    body: MenuCategoryCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> MenuCategoryResponse:
    """Create a new menu category for the admin's restaurant."""
    category = MenuCategory(
        restaurant_id=user.restaurant_id,
        name=body.name,
        sort_order=body.sort_order,
    )
    session.add(category)
    await session.commit()
    await session.refresh(category)
    return MenuCategoryResponse.model_validate(category)


@router.get("/menu-categories", response_model=list[MenuCategoryResponse])
async def list_menu_categories(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[MenuCategoryResponse]:
    """List all menu categories for the admin's restaurant."""
    result = await session.execute(
        select(MenuCategory)
        .where(MenuCategory.restaurant_id == user.restaurant_id)
        .order_by(MenuCategory.sort_order, MenuCategory.name)
    )
    categories = result.scalars().all()
    return [MenuCategoryResponse.model_validate(c) for c in categories]


@router.patch(
    "/menu-categories/{category_id}",
    response_model=MenuCategoryResponse,
)
async def update_menu_category(
    category_id: UUID,
    body: MenuCategoryUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> MenuCategoryResponse:
    """Update a menu category (name, sort_order, is_active)."""
    result = await session.execute(
        select(MenuCategory).where(
            MenuCategory.id == category_id,
            MenuCategory.restaurant_id == user.restaurant_id,
        )
    )
    category = result.scalar_one_or_none()

    if category is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu category not found",
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(category, field, value)

    session.add(category)
    await session.commit()
    await session.refresh(category)
    return MenuCategoryResponse.model_validate(category)


# ─── Menu Items ──────────────────────────────────────────────────────────────


@router.post(
    "/menu-items",
    response_model=MenuItemResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_menu_item(
    body: MenuItemCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> MenuItemResponse:
    """Create a new menu item. ``prep_time_minutes`` is required."""
    # Validate category belongs to the same restaurant (if provided)
    if body.category_id is not None:
        cat_result = await session.execute(
            select(MenuCategory.id).where(
                MenuCategory.id == body.category_id,
                MenuCategory.restaurant_id == user.restaurant_id,
            )
        )
        if cat_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category not found or does not belong to this restaurant",
            )

    item = MenuItem(
        restaurant_id=user.restaurant_id,
        category_id=body.category_id,
        name=body.name,
        description=body.description,
        price=body.price,
        prep_time_minutes=body.prep_time_minutes,
        image_url=body.image_url,
        sort_order=body.sort_order,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return MenuItemResponse.model_validate(item)


@router.get("/menu-items", response_model=list[MenuItemResponse])
async def list_menu_items(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[MenuItemResponse]:
    """List all menu items for the admin's restaurant."""
    result = await session.execute(
        select(MenuItem)
        .where(MenuItem.restaurant_id == user.restaurant_id)
        .order_by(MenuItem.sort_order, MenuItem.name)
    )
    items = result.scalars().all()
    return [MenuItemResponse.model_validate(i) for i in items]


@router.patch("/menu-items/{item_id}", response_model=MenuItemResponse)
async def update_menu_item(
    item_id: UUID,
    body: MenuItemUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> MenuItemResponse:
    """Update a menu item (name, price, is_available, is_active, etc.)."""
    result = await session.execute(
        select(MenuItem).where(
            MenuItem.id == item_id,
            MenuItem.restaurant_id == user.restaurant_id,
        )
    )
    item = result.scalar_one_or_none()

    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu item not found",
        )

    update_data = body.model_dump(exclude_unset=True)

    # Validate category_id if being updated
    if "category_id" in update_data and update_data["category_id"] is not None:
        cat_result = await session.execute(
            select(MenuCategory.id).where(
                MenuCategory.id == update_data["category_id"],
                MenuCategory.restaurant_id == user.restaurant_id,
            )
        )
        if cat_result.scalar_one_or_none() is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Category not found or does not belong to this restaurant",
            )

    for field, value in update_data.items():
        setattr(item, field, value)

    session.add(item)
    await session.commit()
    await session.refresh(item)
    return MenuItemResponse.model_validate(item)


# ─── Presets ─────────────────────────────────────────────────────────────────


@router.get("/settings/presets", response_model=PrepTimePresetsResponse)
async def get_prep_time_presets(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> PrepTimePresetsResponse:
    """Return savory/light prep_time presets from restaurant_settings.

    Frontend uses these to pre-fill ``prep_time_minutes`` when creating items.
    """
    result = await session.execute(
        select(RestaurantSettings).where(
            RestaurantSettings.restaurant_id == user.restaurant_id,
        )
    )
    settings = result.scalar_one_or_none()

    if settings is None:
        # Return sensible defaults if no settings row exists
        return PrepTimePresetsResponse(
            default_savory_minutes=10,
            default_light_minutes=5,
        )

    return PrepTimePresetsResponse(
        default_savory_minutes=settings.default_savory_minutes,
        default_light_minutes=settings.default_light_minutes,
    )
