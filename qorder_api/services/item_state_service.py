"""Item state machine service using compare-and-swap (R4.1–R4.7, R11).

Provides ``ItemStateService.set_status`` which performs an atomic status
transition via a single ``UPDATE ... WHERE status = ANY(:allowed_from)
RETURNING *`` query. If zero rows are returned, another actor already changed
the status → raise 409.

Also provides ``ItemStateService.cancel_item`` for cancelling order items
using the same CAS pattern (R11.1–R11.7).

Also provides ``compute_overdue_level`` — a pure function computing the dynamic
overdue level from ``prep_time_snapshot``, ``requested_at``, and current time
(R5.1, R5.2, R5.4, R5.5, R5.6, R5.7). This value is NEVER stored in the DB.

Key behaviors:
- Forward: pending → cooking → ready → served (can skip intermediate).
- Undo: served → pending ONLY within 120s of served_at (R4.7).
- Cancel: pending/cooking/ready → cancelled (CAS, sets cancelled_by/at/reason).
- Sets served_by/served_at when transitioning to ``served``.
- Clears served_by/served_at when undoing (served → pending).
- Updates table_sessions.last_activity_at after any successful transition.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Set

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.models.enums import CancelledBy, OrderItemStatus
from qorder_api.models.order import OrderItem


class InvalidTransition(Exception):
    """Raised when the requested status transition is not allowed."""


class ConflictError(Exception):
    """Raised when CAS returns 0 rows (someone else changed it first)."""


# ─── Allowed transitions map ────────────────────────────────────────────────
# Key: target status → Value: set of statuses you can come FROM
ALLOWED_FROM: dict[OrderItemStatus, set[OrderItemStatus]] = {
    OrderItemStatus.COOKING: {OrderItemStatus.PENDING},
    OrderItemStatus.READY: {OrderItemStatus.PENDING, OrderItemStatus.COOKING},
    OrderItemStatus.SERVED: {
        OrderItemStatus.PENDING,
        OrderItemStatus.COOKING,
        OrderItemStatus.READY,
    },
    # Undo: served → pending (with time constraint enforced in SQL)
    OrderItemStatus.PENDING: {OrderItemStatus.SERVED},
}


class ItemStateService:
    """Manages order_item status transitions using atomic CAS."""

    @staticmethod
    async def set_status(
        item_id: uuid.UUID,
        to_status: OrderItemStatus,
        actor_user_id: uuid.UUID | None,
        restaurant_id: uuid.UUID,
        session: AsyncSession,
    ) -> OrderItem:
        """Atomically transition an order_item's status.

        Args:
            item_id: The order_item to update.
            to_status: Target status.
            actor_user_id: Staff user who performed the action (None if PIN disabled).
            restaurant_id: Tenant scope for isolation.
            session: SQLAlchemy async session.

        Returns:
            The updated OrderItem.

        Raises:
            InvalidTransition: If to_status is not in the allowed map.
            ConflictError: If CAS returns 0 rows (state already changed).
        """
        # 1. Validate the transition is defined
        if to_status not in ALLOWED_FROM:
            raise InvalidTransition(
                f"Không thể chuyển sang trạng thái '{to_status.value}'."
            )

        allowed_from = ALLOWED_FROM[to_status]
        allowed_from_values = [s.value for s in allowed_from]

        # 2. Build and execute CAS query
        is_undo = (to_status == OrderItemStatus.PENDING)
        is_to_served = (to_status == OrderItemStatus.SERVED)

        if is_undo:
            # Undo: served → pending, enforce 120s window in WHERE
            sql = text("""
                UPDATE order_items
                SET status = :to_status,
                    served_by = NULL,
                    served_at = NULL
                WHERE id = :item_id
                  AND restaurant_id = :restaurant_id
                  AND status = ANY(:allowed_from)
                  AND served_at IS NOT NULL
                  AND now() - served_at <= interval '120 seconds'
                RETURNING *
            """)
            params = {
                "to_status": to_status.value,
                "item_id": item_id,
                "restaurant_id": restaurant_id,
                "allowed_from": allowed_from_values,
            }
        elif is_to_served:
            # Transition to served: set served_by and served_at
            sql = text("""
                UPDATE order_items
                SET status = :to_status,
                    served_by = :actor_user_id,
                    served_at = now()
                WHERE id = :item_id
                  AND restaurant_id = :restaurant_id
                  AND status = ANY(:allowed_from)
                RETURNING *
            """)
            params = {
                "to_status": to_status.value,
                "actor_user_id": actor_user_id,
                "item_id": item_id,
                "restaurant_id": restaurant_id,
                "allowed_from": allowed_from_values,
            }
        else:
            # Forward transition (cooking, ready): no served_by/served_at changes
            sql = text("""
                UPDATE order_items
                SET status = :to_status
                WHERE id = :item_id
                  AND restaurant_id = :restaurant_id
                  AND status = ANY(:allowed_from)
                RETURNING *
            """)
            params = {
                "to_status": to_status.value,
                "item_id": item_id,
                "restaurant_id": restaurant_id,
                "allowed_from": allowed_from_values,
            }

        result = await session.execute(sql, params)
        row = result.mappings().first()

        # 3. CAS check: 0 rows → conflict
        if row is None:
            raise ConflictError(
                "Trạng thái món đã thay đổi bởi người khác hoặc điều kiện không thoả."
            )

        # 4. Update table_sessions.last_activity_at for the parent session
        update_session_sql = text("""
            UPDATE table_sessions
            SET last_activity_at = now()
            WHERE id = (
                SELECT o.table_session_id
                FROM orders o
                WHERE o.id = :order_id
            )
        """)
        await session.execute(
            update_session_sql, {"order_id": row["order_id"]}
        )

        await session.commit()

        # 5. Build and return the OrderItem from the row
        item = _row_to_order_item(row)
        return item

    @staticmethod
    async def cancel_item(
        item_id: uuid.UUID,
        cancelled_by: CancelledBy,
        restaurant_id: uuid.UUID,
        session: AsyncSession,
        allowed_from: Set[OrderItemStatus],
        cancel_reason: str | None = None,
    ) -> OrderItem:
        """Atomically cancel an order_item using CAS pattern (R11).

        Args:
            item_id: The order_item to cancel.
            cancelled_by: Who is cancelling (customer, staff, system).
            restaurant_id: Tenant scope for isolation.
            session: SQLAlchemy async session.
            allowed_from: Set of statuses from which cancel is allowed.
            cancel_reason: Optional reason text.

        Returns:
            The updated OrderItem with status='cancelled'.

        Raises:
            ConflictError: If CAS returns 0 rows (item already served/cancelled
                or changed by another actor).
        """
        allowed_from_values = [s.value for s in allowed_from]

        # CAS cancel query
        sql = text("""
            UPDATE order_items
            SET status = 'cancelled',
                cancelled_by = :cancelled_by,
                cancelled_at = now(),
                cancel_reason = :cancel_reason
            WHERE id = :item_id
              AND restaurant_id = :restaurant_id
              AND status = ANY(:allowed_from)
            RETURNING *
        """)
        params = {
            "cancelled_by": cancelled_by.value,
            "cancel_reason": cancel_reason,
            "item_id": item_id,
            "restaurant_id": restaurant_id,
            "allowed_from": allowed_from_values,
        }

        result = await session.execute(sql, params)
        row = result.mappings().first()

        # CAS check: 0 rows → conflict (item already served/cancelled)
        if row is None:
            raise ConflictError(
                "Không thể huỷ: món đã được phục vụ hoặc đã bị huỷ trước đó."
            )

        # Update table_sessions.last_activity_at for the parent session
        update_session_sql = text("""
            UPDATE table_sessions
            SET last_activity_at = now()
            WHERE id = (
                SELECT o.table_session_id
                FROM orders o
                WHERE o.id = :order_id
            )
        """)
        await session.execute(
            update_session_sql, {"order_id": row["order_id"]}
        )

        await session.commit()

        # Build and return the OrderItem from the row
        item = _row_to_order_item(row)
        return item


def _row_to_order_item(row) -> OrderItem:
    """Convert a raw RETURNING row mapping to an OrderItem instance."""
    item = OrderItem(
        id=row["id"],
        restaurant_id=row["restaurant_id"],
        order_id=row["order_id"],
        menu_item_id=row["menu_item_id"],
        name_snapshot=row["name_snapshot"],
        price_snapshot=row["price_snapshot"],
        prep_time_snapshot=row["prep_time_snapshot"],
        quantity=row["quantity"],
        note=row["note"],
        status=OrderItemStatus(row["status"]),
        requested_at=row["requested_at"],
        served_by=row["served_by"],
        served_at=row["served_at"],
        cancelled_by=row["cancelled_by"],
        cancelled_at=row["cancelled_at"],
        cancel_reason=row["cancel_reason"],
    )
    return item


# ─── Overdue level computation (R5.1, R5.2, R5.5) ───────────────────────────


def compute_overdue_level(
    prep_time_snapshot: int,
    requested_at: datetime,
    now: datetime,
) -> int | None:
    """Compute the dynamic overdue level for a kitchen board item.

    This is a **pure function** — no DB access. The overdue level is NEVER
    stored in the database (Property 6 / R5.5).

    Args:
        prep_time_snapshot: Expected preparation time in minutes. If 0, the
            item is "serve immediately" (beer, soft drinks) and has no countdown.
        requested_at: Timestamp when the item was ordered.
        now: Current time for computation.

    Returns:
        None if ``prep_time_snapshot == 0`` (no countdown, no blinking — R5.1).
        Otherwise an integer level:
          0 — ratio < 1.0  (on time)
          1 — 1.0 ≤ ratio < 1.5  (slightly late)
          2 — 1.5 ≤ ratio < 2.0  (moderately late)
          3 — ratio ≥ 2.0  (very late)
    """
    if prep_time_snapshot == 0:
        return None

    elapsed_seconds = (now - requested_at).total_seconds()
    elapsed_minutes = elapsed_seconds / 60.0
    ratio = elapsed_minutes / prep_time_snapshot

    if ratio < 1.0:
        return 0
    elif ratio < 1.5:
        return 1
    elif ratio < 2.0:
        return 2
    else:
        return 3
