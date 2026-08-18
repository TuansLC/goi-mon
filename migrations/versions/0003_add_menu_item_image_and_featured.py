"""add image_large_url and is_featured to menu_items

Revision ID: 0003_menu_image_featured
Revises: 0002_add_qr_image_url
Create Date: 2026-08-18
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "0003_menu_image_featured"
down_revision = "0002_add_qr_image_url"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "menu_items",
        sa.Column("image_large_url", sa.String(), nullable=True),
    )
    op.add_column(
        "menu_items",
        sa.Column(
            "is_featured",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    # Featured items are read on every customer menu load.
    op.create_index(
        "ix_menu_items_restaurant_featured",
        "menu_items",
        ["restaurant_id", "is_featured"],
    )


def downgrade() -> None:
    op.drop_index("ix_menu_items_restaurant_featured", table_name="menu_items")
    op.drop_column("menu_items", "is_featured")
    op.drop_column("menu_items", "image_large_url")
