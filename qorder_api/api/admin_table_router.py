"""Admin CRUD endpoints for tables + QR token generation (R2.1, R2.5, R2.6, R8.2).

All routes require ``role=admin``. Queries filter by ``restaurant_id`` from the JWT
to enforce tenant isolation. QR images are uploaded to S3-compatible storage (MinIO)
and served via public URL — no auth needed for <img> or <a download>.
"""

from __future__ import annotations

import io
import secrets
from uuid import UUID

import qrcode  # type: ignore[import-untyped]
from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.auth.dependencies import CurrentUser, require_role
from qorder_api.config import get_settings
from qorder_api.db import get_session
from qorder_api.models.restaurant import Restaurant
from qorder_api.models.table import Table
from qorder_api.schemas.table import TableCreate, TableResponse, TableUpdate
from qorder_api.storage import upload_file

router = APIRouter(
    prefix="/admin/tables",
    tags=["admin-tables"],
    dependencies=[Depends(require_role("admin"))],
)


def _generate_qr_token() -> str:
    """Generate a URL-safe random token for QR code mapping."""
    return secrets.token_urlsafe(16)


async def _get_restaurant_slug(
    restaurant_id: UUID, session: AsyncSession
) -> str:
    """Fetch the restaurant slug needed to build QR URLs."""
    result = await session.execute(
        select(Restaurant.slug).where(Restaurant.id == restaurant_id)
    )
    slug = result.scalar_one_or_none()
    if slug is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Restaurant not found",
        )
    return slug


def _build_qr_url(slug: str, qr_token: str) -> str:
    """Construct the full QR URL: {BASE_URL}/{slug}/t/{qr_token}."""
    settings = get_settings()
    return f"{settings.base_url}/{slug}/t/{qr_token}"


def _render_qr_png_bytes(data: str) -> bytes:
    """Render a QR code and return raw PNG bytes."""
    img = qrcode.make(data)
    buffer = io.BytesIO()
    img.save(buffer, format="PNG")
    return buffer.getvalue()


def _upload_qr_image(table_id: UUID, png_bytes: bytes) -> str:
    """Upload QR PNG to S3 storage and return the public URL."""
    key = f"qr/{table_id}.png"
    return upload_file(key, png_bytes, content_type="image/png")


# ─── Endpoints ───────────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=TableResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_table(
    body: TableCreate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> TableResponse:
    """Create a new table with an auto-generated ``qr_token`` (R2.1).

    Also renders and uploads the QR PNG to MinIO so it can be viewed/downloaded
    via a public URL without authentication.
    """
    slug = await _get_restaurant_slug(user.restaurant_id, session)
    qr_token = _generate_qr_token()

    table = Table(
        restaurant_id=user.restaurant_id,
        table_number=body.table_number,
        qr_token=qr_token,
    )
    session.add(table)
    await session.flush()  # assign table.id

    # Render QR → upload to MinIO
    qr_url = _build_qr_url(slug, qr_token)
    png_bytes = _render_qr_png_bytes(qr_url)
    image_url = _upload_qr_image(table.id, png_bytes)
    table.qr_image_url = image_url

    await session.commit()
    await session.refresh(table)
    return TableResponse.model_validate(table)


@router.get("", response_model=list[TableResponse])
async def list_tables(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> list[TableResponse]:
    """List all tables for the admin's restaurant."""
    result = await session.execute(
        select(Table)
        .where(Table.restaurant_id == user.restaurant_id)
        .order_by(Table.table_number)
    )
    tables = result.scalars().all()
    return [TableResponse.model_validate(t) for t in tables]


@router.patch("/{table_id}", response_model=TableResponse)
async def update_table(
    table_id: UUID,
    body: TableUpdate,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> TableResponse:
    """Update a table (table_number, is_active)."""
    result = await session.execute(
        select(Table).where(
            Table.id == table_id,
            Table.restaurant_id == user.restaurant_id,
        )
    )
    table = result.scalar_one_or_none()

    if table is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Table not found",
        )

    update_data = body.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(table, field, value)

    session.add(table)
    await session.commit()
    await session.refresh(table)
    return TableResponse.model_validate(table)


@router.post("/{table_id}/regenerate-qr", response_model=TableResponse)
async def regenerate_qr(
    table_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> TableResponse:
    """Regenerate ``qr_token`` — old QR becomes invalid immediately (R2.6).

    Re-renders the QR PNG and uploads to MinIO (overwrites the same key).
    If the table has an open session, the session stays open; only the QR
    link changes.
    """
    result = await session.execute(
        select(Table).where(
            Table.id == table_id,
            Table.restaurant_id == user.restaurant_id,
        )
    )
    table = result.scalar_one_or_none()

    if table is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Table not found",
        )

    slug = await _get_restaurant_slug(user.restaurant_id, session)
    new_token = _generate_qr_token()
    table.qr_token = new_token

    # Re-render and upload QR image (overwrites same key)
    qr_url = _build_qr_url(slug, new_token)
    png_bytes = _render_qr_png_bytes(qr_url)
    image_url = _upload_qr_image(table.id, png_bytes)
    table.qr_image_url = image_url

    session.add(table)
    await session.commit()
    await session.refresh(table)
    return TableResponse.model_validate(table)


@router.get("/{table_id}/qr")
async def get_qr_image(
    table_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> StreamingResponse:
    """Render the table's QR code as a PNG image on-the-fly (R2.5).

    This endpoint is kept as a fallback for direct download. The preferred
    way to display QR is via ``qr_image_url`` (served from MinIO, no auth needed).
    """
    result = await session.execute(
        select(Table).where(
            Table.id == table_id,
            Table.restaurant_id == user.restaurant_id,
        )
    )
    table = result.scalar_one_or_none()

    if table is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Table not found",
        )

    slug = await _get_restaurant_slug(user.restaurant_id, session)
    qr_url = _build_qr_url(slug, table.qr_token)
    png_bytes = _render_qr_png_bytes(qr_url)

    return StreamingResponse(io.BytesIO(png_bytes), media_type="image/png")
