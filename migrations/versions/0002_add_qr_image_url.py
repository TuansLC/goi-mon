"""add qr_image_url column to tables

Revision ID: 0002_add_qr_image_url
Revises: 0001_initial
Create Date: 2026-08-13
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = "0002_add_qr_image_url"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tables", sa.Column("qr_image_url", sa.String(), nullable=True))


def downgrade() -> None:
    op.drop_column("tables", "qr_image_url")
