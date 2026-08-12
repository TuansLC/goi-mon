"""Staff endpoints for table session operations (R12.2, R6.1, R6.2).

Requires staff or admin JWT. Routes enforce tenant isolation by checking that
the table belongs to the same restaurant_id as the authenticated user.
"""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from qorder_api.auth.dependencies import CurrentUser, require_role
from qorder_api.db import get_session
from qorder_api.models.session import TableSession
from qorder_api.models.table import Table
from qorder_api.realtime import (
    EventTypes,
    RealtimePublisher,
    kitchen_channel,
    session_channel,
)
from qorder_api.redis import get_redis
from qorder_api.schemas.session import (
    CancelledItemSummary,
    CheckoutResponse,
    RestoreResponse,
    SessionResponse,
)
from qorder_api.services.session_service import SessionService

router = APIRouter(
    prefix="/tables",
    tags=["staff-tables"],
    dependencies=[Depends(require_role("staff", "admin"))],
)


@router.post("/{table_id}/open", response_model=SessionResponse)
async def open_table(
    table_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> SessionResponse:
    """Staff manually opens a table session (R12.2).

    Validates that the table belongs to the same restaurant as the user's JWT
    claim to enforce tenant isolation. Calls SessionService.get_or_open with
    ``opened_by=user.sub``.
    """

    # 1. Verify table exists and belongs to the user's restaurant
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
            detail="Bàn không tồn tại hoặc không thuộc quán của bạn.",
        )

    if not table.is_active:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Bàn đã ngừng hoạt động.",
        )

    # 2. Get or open session (race-safe, with opened_by set to staff user)
    table_session = await SessionService.get_or_open(
        table_id=table.id,
        restaurant_id=user.restaurant_id,
        session=session,
        opened_by=user.sub,
    )

    return SessionResponse.model_validate(table_session)


@router.post("/sessions/{session_id}/checkout", response_model=CheckoutResponse)
async def checkout_session(
    session_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> CheckoutResponse:
    """Check out (close) a table session (R6.1, R6.2, R6.6–R6.9).

    Uses compare-and-swap to atomically close the session. If the session was
    already closed/abandoned by another actor, returns 409 Conflict (soft error).

    On success:
    - Auto-cancels all non-served items (system / table_closed).
    - Computes total_amount from served items only.
    - Dismisses all pending staff calls for the session.
    - Publishes ``session.closed`` event to kitchen and session channels.
    - Returns the session info + total + list of auto-cancelled items.
    """

    # 1. Verify session exists and belongs to user's restaurant (tenant isolation)
    result = await session.execute(
        select(TableSession).where(
            TableSession.id == session_id,
            TableSession.restaurant_id == user.restaurant_id,
        )
    )
    table_session = result.scalar_one_or_none()

    if table_session is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phiên bàn không tồn tại hoặc không thuộc quán của bạn.",
        )

    # 2. Perform checkout via CAS
    checkout_result = await SessionService.checkout(
        session_id=session_id,
        restaurant_id=user.restaurant_id,
        session=session,
    )

    if checkout_result is None:
        # CAS lost: session was already closed or abandoned
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Phiên bàn đã được đóng hoặc bỏ trước đó. Không thể checkout lại.",
        )

    # 3. Publish session.closed event to kitchen and session channels
    event_payload = {
        "session": {
            "id": str(checkout_result.session.id),
            "table_id": str(checkout_result.session.table_id),
            "status": "closed",
            "total_amount": str(checkout_result.total_amount),
            "closed_at": checkout_result.session.closed_at.isoformat()
            if checkout_result.session.closed_at
            else None,
        },
    }
    await RealtimePublisher.publish(
        kitchen_channel(user.restaurant_id),
        EventTypes.SESSION_CLOSED,
        event_payload,
        redis_client,
    )
    await RealtimePublisher.publish(
        session_channel(user.restaurant_id, session_id),
        EventTypes.SESSION_CLOSED,
        event_payload,
        redis_client,
    )

    # 4. Build response
    cancelled_summaries = [
        CancelledItemSummary(
            id=item["id"],
            name_snapshot=item["name_snapshot"],
            quantity=item["quantity"],
            status_before=item["status_before"],
        )
        for item in checkout_result.auto_cancelled_items
    ]

    return CheckoutResponse(
        session=SessionResponse.model_validate(checkout_result.session),
        total_amount=checkout_result.total_amount,
        auto_cancelled_items=cancelled_summaries,
        dismissed_calls_count=checkout_result.dismissed_calls_count,
    )


@router.post("/sessions/{session_id}/restore", response_model=RestoreResponse)
async def restore_session(
    session_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> RestoreResponse:
    """Restore or directly check out an abandoned session (R13.5, R13.6, R13.7).

    Two possible outcomes:
    - If the table has NO other open session → restore back to ``open``.
    - If the table ALREADY has an open session → direct checkout (abandoned → closed).

    Blocks the operation if more than 24 hours have passed since ``abandoned_at``.
    """

    try:
        restore_result = await SessionService.restore(
            session_id=session_id,
            restaurant_id=user.restaurant_id,
            session=session,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )

    if restore_result is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Phiên bàn không tồn tại hoặc không thuộc quán của bạn.",
        )

    # Publish realtime event
    if restore_result.action == "restored":
        event_payload = {
            "session": {
                "id": str(restore_result.session.id),
                "table_id": str(restore_result.session.table_id),
                "status": "open",
            },
        }
        await RealtimePublisher.publish(
            kitchen_channel(user.restaurant_id),
            EventTypes.SESSION_RESTORED,
            event_payload,
            redis_client,
        )
        await RealtimePublisher.publish(
            session_channel(user.restaurant_id, session_id),
            EventTypes.SESSION_RESTORED,
            event_payload,
            redis_client,
        )
    else:
        # checked_out path — publish session.closed
        event_payload = {
            "session": {
                "id": str(restore_result.session.id),
                "table_id": str(restore_result.session.table_id),
                "status": "closed",
                "total_amount": str(restore_result.total_amount),
                "closed_at": restore_result.session.closed_at.isoformat()
                if restore_result.session.closed_at
                else None,
            },
        }
        await RealtimePublisher.publish(
            kitchen_channel(user.restaurant_id),
            EventTypes.SESSION_CLOSED,
            event_payload,
            redis_client,
        )
        await RealtimePublisher.publish(
            session_channel(user.restaurant_id, session_id),
            EventTypes.SESSION_CLOSED,
            event_payload,
            redis_client,
        )

    # Build response
    cancelled_summaries = [
        CancelledItemSummary(
            id=item["id"],
            name_snapshot=item["name_snapshot"],
            quantity=item["quantity"],
            status_before=item["status_before"],
        )
        for item in restore_result.auto_cancelled_items
    ]

    return RestoreResponse(
        session=SessionResponse.model_validate(restore_result.session),
        action=restore_result.action,
        total_amount=restore_result.total_amount,
        auto_cancelled_items=cancelled_summaries,
        dismissed_calls_count=restore_result.dismissed_calls_count,
    )
