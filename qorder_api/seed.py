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
import secrets
from decimal import Decimal

from passlib.context import CryptContext
from sqlalchemy import select

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

# bcrypt for both admin passwords and the shared staff PIN (R12.6).
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

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
                    password_hash=_pwd_context.hash(ADMIN_PASSWORD),
                    display_name="Quản trị",
                ),
                User(
                    restaurant_id=restaurant.id,
                    role=UserRole.STAFF,
                    pin_hash=_pwd_context.hash(STAFF_PIN),
                    display_name="Nhân viên",
                ),
            ]
        )

        # --- tables ---
        for number in ("1", "2", "VIP-1"):
            session.add(
                Table(
                    restaurant_id=restaurant.id,
                    table_number=number,
                    qr_token=secrets.token_urlsafe(16),
                )
            )

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
