"""Kitchen endpoints for item status management (R4.1–R4.7, R5, R11.4).

Provides:
- ``GET /kitchen/board`` — snapshot of all active items for the kitchen screen.
- ``POST /kitchen/items/{item_id}/status`` — atomic status transitions.
- ``POST /kitchen/items/{item_id}/cancel`` — staff item cancellation.

All use compare-and-swap where applicable. Requires staff or admin JWT.
Enforces tenant isolation by verifying items belong to the authenticated
user's restaurant.
"""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from qorder_api.auth.dependencies import CurrentUser, require_role
from qorder_api.db import get_session
from qorder_api.models.enums import CancelledBy, OrderItemStatus
from qorder_api.models.order import Order, OrderItem
from qorder_api.realtime import (
    EventTypes,
    RealtimePublisher,
    kitchen_channel,
    session_channel,
)
from qorder_api.redis import get_redis
from qorder_api.schemas.kitchen import (
    CancelItemRequest,
    CancelledItemResponse,
    KitchenBoardItemResponse,
    KitchenBoardResponse,
    KitchenOrderItemResponse,
    SetItemStatusRequest,
)
from qorder_api.schemas.staff_call import StaffCallResponse
from qorder_api.services.item_state_service import (
    ConflictError,
    InvalidTransition,
    ItemStateService,
    compute_overdue_level,
)
from qorder_api.services.staff_call_service import StaffCallService

router = APIRouter(
    prefix="/kitchen",
    tags=["kitchen"],
    dependencies=[Depends(require_role("staff", "admin"))],
)


@router.get(
    "/board",
    response_model=KitchenBoardResponse,
)
async def get_kitchen_board(
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
) -> KitchenBoardResponse:
    """Return all active order items for the kitchen board (R5, R4).

    Returns items with status ``pending``, ``cooking``, or ``ready`` for
    the authenticated user's restaurant. Items are ordered by
    ``requested_at ASC`` (oldest = most urgent first).

    Each item includes a dynamically computed ``overdue_level`` based on
    elapsed time vs ``prep_time_snapshot``. This value is NOT stored in DB.
    """
    # Fetch active items for this restaurant
    active_statuses = [
        OrderItemStatus.PENDING.value,
        OrderItemStatus.COOKING.value,
        OrderItemStatus.READY.value,
    ]

    result = await session.execute(
        select(OrderItem)
        .where(
            OrderItem.restaurant_id == user.restaurant_id,
            OrderItem.status.in_(active_statuses),
        )
        .order_by(OrderItem.requested_at.asc())
    )
    items = result.scalars().all()

    # Compute overdue_level dynamically for each item
    now = datetime.now(timezone.utc)
    board_items: list[KitchenBoardItemResponse] = []
    for item in items:
        level = compute_overdue_level(
            prep_time_snapshot=item.prep_time_snapshot,
            requested_at=item.requested_at,
            now=now,
        )
        board_items.append(
            KitchenBoardItemResponse(
                id=item.id,
                order_id=item.order_id,
                menu_item_id=item.menu_item_id,
                name_snapshot=item.name_snapshot,
                price_snapshot=item.price_snapshot,
                prep_time_snapshot=item.prep_time_snapshot,
                quantity=item.quantity,
                note=item.note,
                status=item.status,
                requested_at=item.requested_at,
                overdue_level=level,
            )
        )

    return KitchenBoardResponse(items=board_items)


@router.post(
    "/items/{item_id}/status",
    response_model=KitchenOrderItemResponse,
)
async def set_item_status(
    item_id: UUID,
    body: SetItemStatusRequest,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> KitchenOrderItemResponse:
    """Atomically change an order item's status (R4.1–R4.7).

    Uses compare-and-swap: if another actor already transitioned the item,
    returns 409 Conflict. Tenant isolation is enforced via restaurant_id in
    the CAS WHERE clause.

    - Forward: pending → cooking → ready → served (can skip intermediate).
    - Undo: served → pending within 120s of served_at.
    - Sets served_by/served_at on transition to served.
    - Clears served_by/served_at on undo.
    - Updates session.last_activity_at after any change.
    """

    # Verify item exists and belongs to user's restaurant (tenant isolation)
    result = await session.execute(
        select(OrderItem.id).where(
            OrderItem.id == item_id,
            OrderItem.restaurant_id == user.restaurant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Món không tồn tại hoặc không thuộc quán của bạn.",
        )

    try:
        updated_item = await ItemStateService.set_status(
            item_id=item_id,
            to_status=body.to,
            actor_user_id=user.sub,
            restaurant_id=user.restaurant_id,
            session=session,
        )
    except InvalidTransition as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        )
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    # Publish item.updated event to kitchen and session channels
    # Resolve session_id from the order's table_session_id
    order_result = await session.execute(
        select(Order.table_session_id).where(Order.id == updated_item.order_id)
    )
    table_session_id = order_result.scalar_one()

    item_payload = {
        "item": {
            "id": str(updated_item.id),
            "status": updated_item.status.value if hasattr(updated_item.status, "value") else updated_item.status,
            "order_id": str(updated_item.order_id),
        },
    }
    await RealtimePublisher.publish(
        kitchen_channel(user.restaurant_id),
        EventTypes.ITEM_UPDATED,
        item_payload,
        redis_client,
    )
    await RealtimePublisher.publish(
        session_channel(user.restaurant_id, table_session_id),
        EventTypes.ITEM_UPDATED,
        item_payload,
        redis_client,
    )

    return KitchenOrderItemResponse.model_validate(updated_item)


@router.post(
    "/items/{item_id}/cancel",
    response_model=CancelledItemResponse,
)
async def cancel_item_staff(
    item_id: UUID,
    user: CurrentUser,
    body: CancelItemRequest | None = None,
    session: AsyncSession = Depends(get_session),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> CancelledItemResponse:
    """Staff cancels an order item (R11.4).

    Allowed from pending, cooking, or ready. Items already served or cancelled
    will return 409 Conflict. Tenant isolation enforced via restaurant_id.
    """

    # Verify item exists and belongs to user's restaurant (tenant isolation)
    result = await session.execute(
        select(OrderItem.id).where(
            OrderItem.id == item_id,
            OrderItem.restaurant_id == user.restaurant_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Món không tồn tại hoặc không thuộc quán của bạn.",
        )

    reason = body.reason if body else None

    try:
        updated_item = await ItemStateService.cancel_item(
            item_id=item_id,
            cancelled_by=CancelledBy.STAFF,
            restaurant_id=user.restaurant_id,
            session=session,
            allowed_from={
                OrderItemStatus.PENDING,
                OrderItemStatus.COOKING,
                OrderItemStatus.READY,
            },
            cancel_reason=reason,
        )
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    # Publish item.cancelled event to kitchen and session channels
    # Resolve session_id from the order's table_session_id
    order_result = await session.execute(
        select(Order.table_session_id).where(Order.id == updated_item.order_id)
    )
    table_session_id = order_result.scalar_one()

    cancel_payload = {
        "item": {
            "id": str(updated_item.id),
            "status": updated_item.status.value if hasattr(updated_item.status, "value") else updated_item.status,
            "cancelled_by": "staff",
            "order_id": str(updated_item.order_id),
        },
    }
    await RealtimePublisher.publish(
        kitchen_channel(user.restaurant_id),
        EventTypes.ITEM_CANCELLED,
        cancel_payload,
        redis_client,
    )
    await RealtimePublisher.publish(
        session_channel(user.restaurant_id, table_session_id),
        EventTypes.ITEM_CANCELLED,
        cancel_payload,
        redis_client,
    )

    return CancelledItemResponse.model_validate(updated_item)



@router.post(
    "/calls/{call_id}/ack",
    response_model=StaffCallResponse,
)
async def ack_staff_call(
    call_id: UUID,
    user: CurrentUser,
    session: AsyncSession = Depends(get_session),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> StaffCallResponse:
    """Acknowledge a pending staff call (R7.3).

    Sets the call status to 'acknowledged' with the current staff member
    as the actor. Publishes staff_call.ack event to kitchen and session channels.
    """
    try:
        call = await StaffCallService.ack(
            call_id=call_id,
            actor_user_id=user.sub,
            restaurant_id=user.restaurant_id,
            session=session,
            redis_client=redis_client,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )

    return StaffCallResponse.model_validate(call)
