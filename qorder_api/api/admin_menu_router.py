"""Admin CRUD endpoints for menu categories and menu items (R8.1, R3.2, R5.3).

All routes inherit the ``/admin`` prefix and ``require_role("admin")`` guard
from the parent admin router. Queries filter by ``restaurant_id`` from the JWT
to enforce tenant isolation.
"""

from __future__ import annotations

import asyncio
import logging
import time
from uuid import UUID

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.auth.dependencies import CurrentUser, require_role
from qorder_api.db import get_session
from qorder_api.images import (
    ALLOWED_CONTENT_TYPES,
    IMAGE_CACHE_CONTROL,
    IMAGE_CONTENT_TYPE,
    MAX_UPLOAD_BYTES,
    ImageValidationError,
    process_menu_image,
)
from qorder_api.models.menu import MenuCategory, MenuItem
from qorder_api.models.restaurant import RestaurantSettings
from qorder_api.storage import delete_file, key_from_public_url, upload_file
from qorder_api.schemas.menu import (
    MenuCategoryCreate,
    MenuCategoryResponse,
    MenuCategoryUpdate,
    MenuItemCreate,
    MenuItemResponse,
    MenuItemUpdate,
    PrepTimePresetsResponse,
)

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["admin-menu"],
    dependencies=[Depends(require_role("admin"))],
)


def _discard_images(*urls: str | None) -> None:
    """Best-effort removal of superseded image objects.

    Failing to delete an old photo must never fail the request — the DB already
    points at the new one, the leftover object is just wasted storage.
    """
    for url in urls:
        if not url:
            continue
        key = key_from_public_url(url)
        if key:
            try:
                delete_file(key)
            except Exception:  # noqa: BLE001 — cleanup is advisory
                logger.warning("Could not delete old image %s", key, exc_info=True)


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
        is_featured=body.is_featured,
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


# ─── Menu Item photos ────────────────────────────────────────────────────────


async def _get_own_item(
    item_id: UUID, restaurant_id: UUID, session: AsyncSession
) -> MenuItem:
    """Fetch a menu item scoped to the caller's restaurant, or raise 404."""
    result = await session.execute(
        select(MenuItem).where(
            MenuItem.id == item_id,
            MenuItem.restaurant_id == restaurant_id,
        )
    )
    item = result.scalar_one_or_none()
    if item is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Menu item not found",
        )
    return item


@router.post("/menu-items/{item_id}/image", response_model=MenuItemResponse)
async def upload_menu_item_image(
    item_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    file: UploadFile = File(...),
) -> MenuItemResponse:
    """Attach a photo to a menu item.

    The upload is normalised into a 400×400 thumbnail plus a max-1000px variant
    (both WebP) and stored under a **versioned** key, so the long cache lifetime
    never serves a stale photo after the owner replaces it.
    """
    item = await _get_own_item(item_id, user.restaurant_id, session)

    if file.content_type not in ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Chỉ nhận ảnh JPEG, PNG hoặc WebP.",
        )

    # Read one byte past the cap so an oversized upload is detectable.
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Ảnh vượt quá {MAX_UPLOAD_BYTES // (1024 * 1024)}MB.",
        )
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Tệp ảnh rỗng.",
        )

    # Pillow decode/resize and the boto3 upload are both blocking.
    try:
        thumb_bytes, large_bytes = await asyncio.to_thread(process_menu_image, raw)
    except ImageValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc

    version = int(time.time())
    previous = (item.image_url, item.image_large_url)

    thumb_url, large_url = await asyncio.gather(
        asyncio.to_thread(
            upload_file,
            f"menu/{item.id}/thumb-{version}.webp",
            thumb_bytes,
            IMAGE_CONTENT_TYPE,
            IMAGE_CACHE_CONTROL,
        ),
        asyncio.to_thread(
            upload_file,
            f"menu/{item.id}/large-{version}.webp",
            large_bytes,
            IMAGE_CONTENT_TYPE,
            IMAGE_CACHE_CONTROL,
        ),
    )

    item.image_url = thumb_url
    item.image_large_url = large_url
    session.add(item)
    await session.commit()
    await session.refresh(item)

    await asyncio.to_thread(_discard_images, *previous)

    return MenuItemResponse.model_validate(item)


@router.delete("/menu-items/{item_id}/image", response_model=MenuItemResponse)
async def delete_menu_item_image(
    item_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> MenuItemResponse:
    """Remove a menu item's photo (the customer screen falls back to a placeholder)."""
    item = await _get_own_item(item_id, user.restaurant_id, session)

    previous = (item.image_url, item.image_large_url)
    item.image_url = None
    item.image_large_url = None
    session.add(item)
    await session.commit()
    await session.refresh(item)

    await asyncio.to_thread(_discard_images, *previous)

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
