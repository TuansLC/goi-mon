"""initial schema — 10 tables, 5 enums, constraints & indexes

Revision ID: 0001_initial
Revises:
Create Date: 2024-01-01 00:00:00.000000

Creates the full QOrder MVP schema:
- ``pgcrypto`` extension for ``gen_random_uuid()``.
- 5 native enum types.
- 10 business tables, all carrying ``restaurant_id`` (multi-tenant).
- CHECK constraints, unique constraints and indexes (incl. the partial
  "one open session per table" unique index).
"""
from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# --- Native enum types (created explicitly; create_type=False on columns) -----
order_item_status = postgresql.ENUM(
    "pending", "cooking", "ready", "served", "cancelled",
    name="order_item_status", create_type=False,
)
session_status = postgresql.ENUM(
    "open", "closed", "abandoned",
    name="session_status", create_type=False,
)
user_role = postgresql.ENUM(
    "staff", "admin",
    name="user_role", create_type=False,
)
cancelled_by = postgresql.ENUM(
    "customer", "staff", "system",
    name="cancelled_by", create_type=False,
)
staff_call_status = postgresql.ENUM(
    "pending", "acknowledged",
    name="staff_call_status", create_type=False,
)

_ALL_ENUMS = (
    order_item_status,
    session_status,
    user_role,
    cancelled_by,
    staff_call_status,
)


def _uuid_pk() -> sa.Column:
    return sa.Column(
        "id",
        postgresql.UUID(as_uuid=True),
        primary_key=True,
        server_default=sa.text("gen_random_uuid()"),
    )


def _tstz(name: str, *, nullable: bool = True, default_now: bool = False) -> sa.Column:
    return sa.Column(
        name,
        sa.TIMESTAMP(timezone=True),
        nullable=nullable,
        server_default=sa.text("now()") if default_now else None,
    )


def upgrade() -> None:
    bind = op.get_bind()

    # gen_random_uuid() lives in pgcrypto on PostgreSQL 16.
    op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto")

    for enum in _ALL_ENUMS:
        enum.create(bind, checkfirst=True)

    # --- restaurants ---------------------------------------------------------
    op.create_table(
        "restaurants",
        _uuid_pk(),
        sa.Column("slug", sa.String(), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("phone", sa.String(), nullable=True),
        sa.Column("address", sa.Text(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _tstz("created_at", nullable=False, default_now=True),
        _tstz("updated_at", nullable=False, default_now=True),
        sa.UniqueConstraint("slug", name="uq_restaurants_slug"),
    )

    # --- restaurant_settings (1-1) ------------------------------------------
    op.create_table(
        "restaurant_settings",
        sa.Column(
            "restaurant_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("restaurants.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("currency", sa.String(), nullable=False, server_default=sa.text("'VND'")),
        sa.Column("logo_url", sa.String(), nullable=True),
        sa.Column("timezone", sa.String(), nullable=False, server_default=sa.text("'Asia/Ho_Chi_Minh'")),
        sa.Column("default_savory_minutes", sa.Integer(), nullable=False, server_default=sa.text("10")),
        sa.Column("default_light_minutes", sa.Integer(), nullable=False, server_default=sa.text("5")),
        sa.Column("session_timeout_hours", sa.Integer(), nullable=False, server_default=sa.text("6")),
        sa.Column("kitchen_screen_requires_pin", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("staff_call_cooldown_seconds", sa.Integer(), nullable=False, server_default=sa.text("60")),
        sa.Column("report_sheet_id", sa.String(), nullable=True),
        sa.Column("report_sync_cron", sa.String(), nullable=False, server_default=sa.text("'0 * * * *'")),
        sa.Column("bill_footer_note", sa.Text(), nullable=True),
        _tstz("updated_at", nullable=False, default_now=True),
    )

    # --- users ---------------------------------------------------------------
    op.create_table(
        "users",
        _uuid_pk(),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", user_role, nullable=False),
        sa.Column("email", sa.String(), nullable=True),
        sa.Column("password_hash", sa.String(), nullable=True),
        sa.Column("pin_hash", sa.String(), nullable=True),
        sa.Column("display_name", sa.String(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _tstz("created_at", nullable=False, default_now=True),
        sa.UniqueConstraint("restaurant_id", "email", name="uq_users_restaurant_email"),
        sa.CheckConstraint(
            "(role = 'admin' AND email IS NOT NULL AND password_hash IS NOT NULL)"
            " OR (role = 'staff' AND pin_hash IS NOT NULL)",
            name="ck_users_role_credentials",
        ),
    )

    # --- tables --------------------------------------------------------------
    op.create_table(
        "tables",
        _uuid_pk(),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_number", sa.String(), nullable=False),
        sa.Column("qr_token", sa.String(), nullable=False),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _tstz("created_at", nullable=False, default_now=True),
        sa.UniqueConstraint("qr_token", name="uq_tables_qr_token"),
        sa.UniqueConstraint("restaurant_id", "table_number", name="uq_tables_restaurant_number"),
    )

    # --- menu_categories -----------------------------------------------------
    op.create_table(
        "menu_categories",
        _uuid_pk(),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        _tstz("created_at", nullable=False, default_now=True),
    )

    # --- menu_items ----------------------------------------------------------
    op.create_table(
        "menu_items",
        _uuid_pk(),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("category_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("menu_categories.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("price", sa.Numeric(12, 2), nullable=False),
        sa.Column("prep_time_minutes", sa.Integer(), nullable=False),
        sa.Column("is_available", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("image_url", sa.String(), nullable=True),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default=sa.text("0")),
        _tstz("created_at", nullable=False, default_now=True),
        _tstz("updated_at", nullable=False, default_now=True),
        sa.CheckConstraint("prep_time_minutes >= 0", name="ck_menu_items_prep_time_nonneg"),
    )

    # --- table_sessions ------------------------------------------------------
    op.create_table(
        "table_sessions",
        _uuid_pk(),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", session_status, nullable=False, server_default=sa.text("'open'")),
        sa.Column("opened_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        _tstz("opened_at", nullable=False, default_now=True),
        _tstz("last_activity_at", nullable=False, default_now=True),
        _tstz("closed_at", nullable=True),
        _tstz("abandoned_at", nullable=True),
        sa.Column("total_amount", sa.Numeric(12, 2), nullable=True),
    )
    op.create_index(
        "uq_one_open_session_per_table",
        "table_sessions",
        ["table_id"],
        unique=True,
        postgresql_where=sa.text("status = 'open'"),
    )
    op.create_index("ix_table_sessions_table_status", "table_sessions", ["table_id", "status"])
    op.create_index("ix_table_sessions_status_activity", "table_sessions", ["status", "last_activity_at"])

    # --- orders --------------------------------------------------------------
    op.create_table(
        "orders",
        _uuid_pk(),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("table_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        _tstz("created_at", nullable=False, default_now=True),
    )

    # --- order_items ---------------------------------------------------------
    op.create_table(
        "order_items",
        _uuid_pk(),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("order_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("orders.id", ondelete="CASCADE"), nullable=False),
        sa.Column("menu_item_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("menu_items.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("name_snapshot", sa.String(), nullable=False),
        sa.Column("price_snapshot", sa.Numeric(12, 2), nullable=False),
        sa.Column("prep_time_snapshot", sa.Integer(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("status", order_item_status, nullable=False, server_default=sa.text("'pending'")),
        _tstz("requested_at", nullable=False, default_now=True),
        sa.Column("served_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        _tstz("served_at", nullable=True),
        sa.Column("cancelled_by", cancelled_by, nullable=True),
        _tstz("cancelled_at", nullable=True),
        sa.Column("cancel_reason", sa.String(), nullable=True),
        sa.CheckConstraint("prep_time_snapshot >= 0", name="ck_order_items_prep_time_nonneg"),
        sa.CheckConstraint("quantity > 0", name="ck_order_items_quantity_positive"),
    )
    op.create_index("ix_order_items_order", "order_items", ["order_id"])
    op.create_index("ix_order_items_restaurant_status", "order_items", ["restaurant_id", "status"])

    # --- staff_calls ---------------------------------------------------------
    op.create_table(
        "staff_calls",
        _uuid_pk(),
        sa.Column("restaurant_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("restaurants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("tables.id", ondelete="CASCADE"), nullable=False),
        sa.Column("table_session_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("table_sessions.id", ondelete="CASCADE"), nullable=False),
        sa.Column("status", staff_call_status, nullable=False, server_default=sa.text("'pending'")),
        _tstz("created_at", nullable=False, default_now=True),
        _tstz("acknowledged_at", nullable=True),
        sa.Column("acknowledged_by", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_table("staff_calls")
    op.drop_index("ix_order_items_restaurant_status", table_name="order_items")
    op.drop_index("ix_order_items_order", table_name="order_items")
    op.drop_table("order_items")
    op.drop_table("orders")
    op.drop_index("ix_table_sessions_status_activity", table_name="table_sessions")
    op.drop_index("ix_table_sessions_table_status", table_name="table_sessions")
    op.drop_index("uq_one_open_session_per_table", table_name="table_sessions")
    op.drop_table("table_sessions")
    op.drop_table("menu_items")
    op.drop_table("menu_categories")
    op.drop_table("tables")
    op.drop_table("users")
    op.drop_table("restaurant_settings")
    op.drop_table("restaurants")

    bind = op.get_bind()
    for enum in reversed(_ALL_ENUMS):
        enum.drop(bind, checkfirst=True)
