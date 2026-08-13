"""Idempotent development seed data for QOrder.

Inserts one restaurant with its settings, an admin (email + password) and a
staff account (shared PIN), a handful of tables, and a small menu that includes
at least one ``prep_time_minutes = 0`` drink (no countdown — R5.1).

Run with::

    python -m qorder_api.seed

Safe to run repeatedly: it looks up the restaurant by ``slug`` and skips seeding
if it already exists.
"""

from __future__ import annotations

import asyncio
import io
import secrets
from decimal import Decimal

import qrcode  # type: ignore[import-untyped]
from sqlalchemy import select

from qorder_api.auth.passwords import hash_password, hash_pin
from qorder_api.config import get_settings
from qorder_api.db import async_session_factory
from qorder_api.models import (
    MenuCategory,
    MenuItem,
    Restaurant,
    RestaurantSettings,
    Table,
    User,
    UserRole,
)
from qorder_api.storage import upload_file

# Hashing goes through qorder_api.auth.passwords so the seed uses the exact same
# bcrypt path as login verification (passlib is incompatible with bcrypt>=4.1).

RESTAURANT_SLUG = "bia-hoi-demo"
ADMIN_EMAIL = "admin@qorder.local"
ADMIN_PASSWORD = "admin1234"  # noqa: S105 — dev seed only
STAFF_PIN = "1234"  # noqa: S105 — dev seed only


async def seed() -> None:
    """Populate the database with a demo tenant if not already present."""

    async with async_session_factory() as session:
        existing = await session.scalar(
            select(Restaurant).where(Restaurant.slug == RESTAURANT_SLUG)
        )
        if existing is not None:
            print(f"Seed skipped: restaurant '{RESTAURANT_SLUG}' already exists.")
            return

        # --- tenant + settings ---
        restaurant = Restaurant(
            slug=RESTAURANT_SLUG,
            name="Bia Hơi Demo",
            phone="0900000000",
            address="123 Đường Bia, Hà Nội",
        )
        restaurant.settings = RestaurantSettings(
            currency="VND",
            timezone="Asia/Ho_Chi_Minh",
            bill_footer_note="Cảm ơn quý khách!",
        )
        session.add(restaurant)
        await session.flush()  # assign restaurant.id

        # --- users: 1 admin + 1 shared-PIN staff ---
        session.add_all(
            [
                User(
                    restaurant_id=restaurant.id,
                    role=UserRole.ADMIN,
                    email=ADMIN_EMAIL,
                    password_hash=hash_password(ADMIN_PASSWORD),
                    display_name="Quản trị",
                ),
                User(
                    restaurant_id=restaurant.id,
                    role=UserRole.STAFF,
                    pin_hash=hash_pin(STAFF_PIN),
                    display_name="Nhân viên",
                ),
            ]
        )

        # --- tables + QR images ---
        tables: list[Table] = []
        for number in ("1", "2", "VIP-1"):
            t = Table(
                restaurant_id=restaurant.id,
                table_number=number,
                qr_token=secrets.token_urlsafe(16),
            )
            session.add(t)
            tables.append(t)

        await session.flush()  # assign table ids

        # Upload QR images to MinIO
        settings = get_settings()
        for t in tables:
            qr_url = f"{settings.base_url}/{RESTAURANT_SLUG}/t/{t.qr_token}"
            img = qrcode.make(qr_url)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            key = f"qr/{t.id}.png"
            t.qr_image_url = upload_file(key, buf.getvalue(), content_type="image/png")

        # --- menu categories + items ---
        cat_food = MenuCategory(
            restaurant_id=restaurant.id, name="Đồ nhắm", sort_order=1
        )
        cat_drink = MenuCategory(
            restaurant_id=restaurant.id, name="Đồ uống", sort_order=2
        )
        session.add_all([cat_food, cat_drink])
        await session.flush()  # assign category ids

        session.add_all(
            [
                MenuItem(
                    restaurant_id=restaurant.id,
                    category_id=cat_food.id,
                    name="Lạc luộc",
                    description="Đĩa lạc luộc nóng",
                    price=Decimal("20000.00"),
                    prep_time_minutes=5,
                    sort_order=1,
                ),
                MenuItem(
                    restaurant_id=restaurant.id,
                    category_id=cat_food.id,
                    name="Nem chua rán",
                    description="Nem chua rán giòn",
                    price=Decimal("45000.00"),
                    prep_time_minutes=10,
                    sort_order=2,
                ),
                # prep_time_minutes = 0 → served immediately, no countdown (R5.1).
                MenuItem(
                    restaurant_id=restaurant.id,
                    category_id=cat_drink.id,
                    name="Bia hơi (cốc)",
                    description="Bia hơi tươi",
                    price=Decimal("10000.00"),
                    prep_time_minutes=0,
                    sort_order=1,
                ),
                MenuItem(
                    restaurant_id=restaurant.id,
                    category_id=cat_drink.id,
                    name="Trà đá",
                    price=Decimal("3000.00"),
                    prep_time_minutes=0,
                    sort_order=2,
                ),
            ]
        )

        await session.commit()
        print(
            "Seed complete:\n"
            f"  restaurant slug = {RESTAURANT_SLUG}\n"
            f"  admin login     = {ADMIN_EMAIL} / {ADMIN_PASSWORD}\n"
            f"  staff PIN       = {STAFF_PIN}\n"
            "  tables          = 1, 2, VIP-1\n"
            "  menu items      = 4 (incl. 2 drinks with prep_time_minutes=0)"
        )


if __name__ == "__main__":
    asyncio.run(seed())
