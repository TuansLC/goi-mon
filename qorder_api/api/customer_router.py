"""Public customer-facing endpoints (R2.2, R2.3, R3.1, R3.2, R3.3, R4.8, R11.2).

QR-scanned URLs resolve to ``GET /t/{qr_token}`` which returns the restaurant,
table, and full menu. ``GET /t/{qr_token}/session`` returns the session snapshot
for client resync after reconnection. ``POST /t/{qr_token}/orders`` creates a
new order. ``POST /t/{qr_token}/items/{item_id}/cancel`` allows a customer to
cancel a pending item. No authentication is required — the customer is anonymous (R12.1).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.db import get_session
from qorder_api.models.enums import CancelledBy, OrderItemStatus, SessionStatus
from qorder_api.models.menu import MenuCategory, MenuItem
from qorder_api.models.order import Order, OrderItem
from qorder_api.models.restaurant import Restaurant
from qorder_api.models.table import Table
from qorder_api.schemas.customer import (
    CreateOrderRequest,
    CreateOrderResponse,
    CustomerMenuCategoryResponse,
    CustomerMenuItemResponse,
    OrderItemResponse,
    QRResolveResponse,
    QRRestaurantInfo,
    QRTableInfo,
)
from qorder_api.schemas.kitchen import CancelItemRequest, CancelledItemResponse
from qorder_api.schemas.session import (
    OrderItemSnapshotResponse,
    SessionSnapshotResponse,
)
from qorder_api.schemas.staff_call import StaffCallCooldownResponse, StaffCallResponse
from qorder_api.realtime import (
    EventTypes,
    RealtimePublisher,
    kitchen_channel,
    session_channel,
)
from qorder_api.redis import get_redis
from qorder_api.services.item_state_service import ConflictError, ItemStateService
from qorder_api.services.session_service import SessionService
from qorder_api.services.staff_call_service import StaffCallService

router = APIRouter(tags=["customer"])


@router.get("/t/{qr_token}", response_model=QRResolveResponse)
async def resolve_qr(
    qr_token: str,
    session: AsyncSession = Depends(get_session),
) -> QRResolveResponse:
    """Resolve a QR token into restaurant + table + menu for the customer.

    Returns 404 with a friendly message when the token is invalid, the table
    is inactive, or the restaurant is inactive.
    """

    # 1. Look up the table by qr_token (must be active)
    table_result = await session.execute(
        select(Table).where(
            Table.qr_token == qr_token,
            Table.is_active.is_(True),
        )
    )
    table = table_result.scalar_one_or_none()

    if table is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mã QR không hợp lệ hoặc bàn đã ngừng hoạt động.",
        )

    # 2. Look up the restaurant (must be active)
    restaurant_result = await session.execute(
        select(Restaurant).where(
            Restaurant.id == table.restaurant_id,
            Restaurant.is_active.is_(True),
        )
    )
    restaurant = restaurant_result.scalar_one_or_none()

    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nhà hàng hiện không hoạt động.",
        )

    # Restaurant.settings is loaded via selectin (lazy="selectin" on the relationship)
    settings = restaurant.settings
    currency = settings.currency if settings else "VND"
    logo_url = settings.logo_url if settings else None

    # 3. Fetch active menu categories ordered by sort_order
    categories_result = await session.execute(
        select(MenuCategory)
        .where(
            MenuCategory.restaurant_id == restaurant.id,
            MenuCategory.is_active.is_(True),
        )
        .order_by(MenuCategory.sort_order)
    )
    categories = categories_result.scalars().all()

    # 4. Fetch active menu items for the restaurant
    items_result = await session.execute(
        select(MenuItem)
        .where(
            MenuItem.restaurant_id == restaurant.id,
            MenuItem.is_active.is_(True),
        )
        .order_by(MenuItem.sort_order)
    )
    items = items_result.scalars().all()

    # 5. Group items by category_id
    items_by_category: dict[object, list[MenuItem]] = defaultdict(list)
    for item in items:
        items_by_category[item.category_id].append(item)

    # 6. Build response
    menu: list[CustomerMenuCategoryResponse] = []
    for cat in categories:
        cat_items = items_by_category.get(cat.id, [])
        menu.append(
            CustomerMenuCategoryResponse(
                id=cat.id,
                name=cat.name,
                sort_order=cat.sort_order,
                items=[
                    CustomerMenuItemResponse.model_validate(item)
                    for item in cat_items
                ],
            )
        )

    return QRResolveResponse(
        restaurant=QRRestaurantInfo(
            name=restaurant.name,
            slug=restaurant.slug,
            currency=currency,
            logo_url=logo_url,
        ),
        table=QRTableInfo(
            id=table.id,
            table_number=table.table_number,
        ),
        menu=menu,
    )



@router.get("/t/{qr_token}/session", response_model=SessionSnapshotResponse)
async def get_session_snapshot(
    qr_token: str,
    session: AsyncSession = Depends(get_session),
) -> SessionSnapshotResponse:
    """Return the current open session + all its order items for client resync (R4.8).

    Steps:
    1. Resolve qr_token → table (must be active, restaurant must be active)
    2. Call SessionService.get_or_open(table_id, restaurant_id) to get/create session
    3. Fetch all orders + order_items for this session
    4. Return session + items snapshot
    """

    # 1. Look up the table by qr_token (must be active)
    table_result = await session.execute(
        select(Table).where(
            Table.qr_token == qr_token,
            Table.is_active.is_(True),
        )
    )
    table = table_result.scalar_one_or_none()

    if table is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mã QR không hợp lệ hoặc bàn đã ngừng hoạt động.",
        )

    # 2. Look up the restaurant (must be active)
    restaurant_result = await session.execute(
        select(Restaurant).where(
            Restaurant.id == table.restaurant_id,
            Restaurant.is_active.is_(True),
        )
    )
    restaurant = restaurant_result.scalar_one_or_none()

    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nhà hàng hiện không hoạt động.",
        )

    # 3. Get or open the session (race-safe)
    table_session = await SessionService.get_or_open(
        table_id=table.id,
        restaurant_id=restaurant.id,
        session=session,
    )

    # 4. Fetch all order items across all orders of this session
    items_result = await session.execute(
        select(OrderItem)
        .join(Order, OrderItem.order_id == Order.id)
        .where(Order.table_session_id == table_session.id)
        .order_by(OrderItem.requested_at)
    )
    items = items_result.scalars().all()

    # 5. Build response
    return SessionSnapshotResponse(
        id=table_session.id,
        restaurant_id=table_session.restaurant_id,
        table_id=table_session.table_id,
        status=table_session.status,
        opened_by=table_session.opened_by,
        opened_at=table_session.opened_at,
        last_activity_at=table_session.last_activity_at,
        closed_at=table_session.closed_at,
        abandoned_at=table_session.abandoned_at,
        total_amount=table_session.total_amount,
        items=[OrderItemSnapshotResponse.model_validate(item) for item in items],
    )


@router.post(
    "/t/{qr_token}/orders",
    response_model=CreateOrderResponse,
    status_code=status.HTTP_201_CREATED,
)
async def create_order(
    qr_token: str,
    body: CreateOrderRequest,
    session: AsyncSession = Depends(get_session),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> CreateOrderResponse:
    """Create a new order for the current table session (R3.3, R3.4, R3.5, R3.6, R6.6).

    Steps:
    a. Resolve qr_token → table (active) → restaurant (active)
    b. Get or open session via SessionService.get_or_open()
    c. Validate session status == 'open' (reject if closed/abandoned)
    d. Validate items list is non-empty (Pydantic handles this via min_length=1)
    e. For each item: look up MenuItem, verify is_available
    f. Create Order record
    g. Create OrderItem records with snapshots
    h. Update session.last_activity_at
    i. Commit and return response
    """

    # a. Look up the table by qr_token (must be active)
    table_result = await session.execute(
        select(Table).where(
            Table.qr_token == qr_token,
            Table.is_active.is_(True),
        )
    )
    table = table_result.scalar_one_or_none()

    if table is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mã QR không hợp lệ hoặc bàn đã ngừng hoạt động.",
        )

    # Look up the restaurant (must be active)
    restaurant_result = await session.execute(
        select(Restaurant).where(
            Restaurant.id == table.restaurant_id,
            Restaurant.is_active.is_(True),
        )
    )
    restaurant = restaurant_result.scalar_one_or_none()

    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nhà hàng hiện không hoạt động.",
        )

    # b. Get or open session
    table_session = await SessionService.get_or_open(
        table_id=table.id,
        restaurant_id=restaurant.id,
        session=session,
    )

    # c. Validate session is open (R6.6)
    if table_session.status != SessionStatus.OPEN:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Phiên bàn đã đóng, không thể thêm order.",
        )

    # e. Validate each item: exists, belongs to restaurant, is_available
    menu_items_map: dict = {}
    for req_item in body.items:
        mi_result = await session.execute(
            select(MenuItem).where(
                MenuItem.id == req_item.menu_item_id,
                MenuItem.restaurant_id == restaurant.id,
                MenuItem.is_active.is_(True),
            )
        )
        menu_item = mi_result.scalar_one_or_none()

        if menu_item is None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Món không tồn tại hoặc đã ngừng phục vụ (id: {req_item.menu_item_id}).",
            )

        if not menu_item.is_available:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Món '{menu_item.name}' hiện đã hết.",
            )

        menu_items_map[req_item.menu_item_id] = menu_item

    # f. Create Order
    now = datetime.now(timezone.utc)
    order = Order(
        restaurant_id=restaurant.id,
        table_session_id=table_session.id,
    )
    session.add(order)
    await session.flush()

    # g. Create OrderItems with snapshots
    order_items: list[OrderItem] = []
    for req_item in body.items:
        mi = menu_items_map[req_item.menu_item_id]
        oi = OrderItem(
            restaurant_id=restaurant.id,
            order_id=order.id,
            menu_item_id=mi.id,
            name_snapshot=mi.name,
            price_snapshot=mi.price,
            prep_time_snapshot=mi.prep_time_minutes,
            quantity=req_item.quantity,
            note=req_item.note,
            requested_at=now,
        )
        session.add(oi)
        order_items.append(oi)

    # h. Update session.last_activity_at
    table_session.last_activity_at = now
    session.add(table_session)

    # i. Commit and refresh to get DB-generated fields (id, created_at, status defaults)
    await session.flush()
    await session.commit()
    await session.refresh(order)
    for oi in order_items:
        await session.refresh(oi)

    # Publish order.created event to kitchen and session channels
    order_payload = {
        "order": {
            "id": str(order.id),
            "table_session_id": str(order.table_session_id),
            "items": [
                {
                    "id": str(oi.id),
                    "name_snapshot": oi.name_snapshot,
                    "quantity": oi.quantity,
                    "status": oi.status.value if hasattr(oi.status, "value") else oi.status,
                }
                for oi in order_items
            ],
        },
    }
    await RealtimePublisher.publish(
        kitchen_channel(restaurant.id),
        EventTypes.ORDER_CREATED,
        order_payload,
        redis_client,
    )
    await RealtimePublisher.publish(
        session_channel(restaurant.id, table_session.id),
        EventTypes.ORDER_CREATED,
        order_payload,
        redis_client,
    )

    # Build response
    return CreateOrderResponse(
        id=order.id,
        table_session_id=order.table_session_id,
        created_at=order.created_at,
        items=[OrderItemResponse.model_validate(oi) for oi in order_items],
    )



@router.post(
    "/t/{qr_token}/items/{item_id}/cancel",
    response_model=CancelledItemResponse,
)
async def cancel_item_customer(
    qr_token: str,
    item_id: UUID,
    body: CancelItemRequest | None = None,
    session: AsyncSession = Depends(get_session),
    redis_client: aioredis.Redis = Depends(get_redis),
) -> CancelledItemResponse:
    """Customer cancels a pending order item (R11.2, R11.3).

    The customer can only cancel items that are still 'pending'. Items
    already in cooking/ready/served/cancelled will return 409 Conflict.
    The customer can only cancel items from their own session (via qr_token).
    """

    # 1. Resolve qr_token → table (must be active)
    table_result = await session.execute(
        select(Table).where(
            Table.qr_token == qr_token,
            Table.is_active.is_(True),
        )
    )
    table = table_result.scalar_one_or_none()

    if table is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mã QR không hợp lệ hoặc bàn đã ngừng hoạt động.",
        )

    # 2. Look up the restaurant (must be active)
    restaurant_result = await session.execute(
        select(Restaurant).where(
            Restaurant.id == table.restaurant_id,
            Restaurant.is_active.is_(True),
        )
    )
    restaurant = restaurant_result.scalar_one_or_none()

    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nhà hàng hiện không hoạt động.",
        )

    # 3. Get or open the session for this table
    table_session = await SessionService.get_or_open(
        table_id=table.id,
        restaurant_id=restaurant.id,
        session=session,
    )

    # 4. Verify item belongs to an order within this session
    item_check = await session.execute(
        select(OrderItem.id)
        .join(Order, OrderItem.order_id == Order.id)
        .where(
            OrderItem.id == item_id,
            Order.table_session_id == table_session.id,
            OrderItem.restaurant_id == restaurant.id,
        )
    )
    if item_check.scalar_one_or_none() is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Món không tồn tại hoặc không thuộc phiên của bạn.",
        )

    # 5. Cancel the item (only from pending)
    reason = body.reason if body else None

    try:
        updated_item = await ItemStateService.cancel_item(
            item_id=item_id,
            cancelled_by=CancelledBy.CUSTOMER,
            restaurant_id=restaurant.id,
            session=session,
            allowed_from={OrderItemStatus.PENDING},
            cancel_reason=reason,
        )
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        )

    # Publish item.cancelled event to kitchen and session channels
    cancel_payload = {
        "item": {
            "id": str(updated_item.id),
            "status": updated_item.status.value if hasattr(updated_item.status, "value") else updated_item.status,
            "cancelled_by": "customer",
        },
    }
    await RealtimePublisher.publish(
        kitchen_channel(restaurant.id),
        EventTypes.ITEM_CANCELLED,
        cancel_payload,
        redis_client,
    )
    await RealtimePublisher.publish(
        session_channel(restaurant.id, table_session.id),
        EventTypes.ITEM_CANCELLED,
        cancel_payload,
        redis_client,
    )

    return CancelledItemResponse.model_validate(updated_item)



@router.post(
    "/t/{qr_token}/call",
    response_model=StaffCallResponse | StaffCallCooldownResponse,
    responses={
        201: {"model": StaffCallResponse, "description": "Staff call created"},
        200: {"model": StaffCallCooldownResponse, "description": "Within cooldown"},
    },
)
async def call_staff(
    qr_token: str,
    session: AsyncSession = Depends(get_session),
    redis_client: aioredis.Redis = Depends(get_redis),
):
    """Customer calls staff to their table (R7.1, R7.2, R7.4).

    If within cooldown (60s default per table), returns 200 with a soft message.
    Otherwise creates a pending staff call and publishes realtime event.
    Also updates session.last_activity_at to prevent auto-abandon (R13.2).
    """
    from starlette.responses import JSONResponse

    # 1. Resolve qr_token → table (must be active)
    table_result = await session.execute(
        select(Table).where(
            Table.qr_token == qr_token,
            Table.is_active.is_(True),
        )
    )
    table = table_result.scalar_one_or_none()

    if table is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Mã QR không hợp lệ hoặc bàn đã ngừng hoạt động.",
        )

    # 2. Look up the restaurant (must be active)
    restaurant_result = await session.execute(
        select(Restaurant).where(
            Restaurant.id == table.restaurant_id,
            Restaurant.is_active.is_(True),
        )
    )
    restaurant = restaurant_result.scalar_one_or_none()

    if restaurant is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Nhà hàng hiện không hoạt động.",
        )

    # 3. Get or open the session
    table_session = await SessionService.get_or_open(
        table_id=table.id,
        restaurant_id=restaurant.id,
        session=session,
    )

    # 4. Call StaffCallService.create
    call = await StaffCallService.create(
        table_id=table.id,
        table_session_id=table_session.id,
        restaurant_id=restaurant.id,
        session=session,
        redis_client=redis_client,
    )

    if call is None:
        # Within cooldown — soft rejection
        return JSONResponse(
            status_code=200,
            content=StaffCallCooldownResponse(
                message="Đã gửi yêu cầu, nhân viên đang tới."
            ).model_dump(),
        )

    # Created successfully
    return JSONResponse(
        status_code=201,
        content=StaffCallResponse.model_validate(call).model_dump(mode="json"),
    )
