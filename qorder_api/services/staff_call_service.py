"""Staff call service (R7.1–R7.4, R13.2).

Provides:
- ``create``: Create a staff call with per-table cooldown.
- ``ack``: Acknowledge a pending staff call.
- ``dismiss_pending``: Bulk-dismiss all pending calls for a session (reused by
  checkout and auto-abandon sweep).
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

import redis.asyncio as aioredis

from qorder_api.models.enums import StaffCallStatus
from qorder_api.models.restaurant import RestaurantSettings
from qorder_api.models.staff_call import StaffCall
from qorder_api.realtime import (
    EventTypes,
    RealtimePublisher,
    kitchen_channel,
    session_channel,
)


# Default cooldown if no restaurant_settings row exists.
_DEFAULT_COOLDOWN_SECONDS = 60


class StaffCallService:
    """Manages staff-call lifecycle."""

    @staticmethod
    async def create(
        table_id: uuid.UUID,
        table_session_id: uuid.UUID,
        restaurant_id: uuid.UUID,
        session: AsyncSession,
        redis_client: aioredis.Redis,
    ) -> StaffCall | None:
        """Create a staff call, respecting per-table cooldown (R7.4).

        Returns the new StaffCall if created, or None if within cooldown.
        Also updates session.last_activity_at to prevent auto-abandon (R13.2).
        """
        # 1. Read cooldown from restaurant_settings
        cooldown = await _get_cooldown(restaurant_id, session)

        # 2. Check if a recent call exists within cooldown window
        recent_check = await session.execute(
            text("""
                SELECT 1 FROM staff_calls
                WHERE table_id = :table_id
                  AND created_at > now() - make_interval(secs => :cooldown)
                LIMIT 1
            """),
            {"table_id": table_id, "cooldown": cooldown},
        )
        if recent_check.scalar_one_or_none() is not None:
            return None  # Within cooldown — skip

        # 3. Create new StaffCall record
        call = StaffCall(
            restaurant_id=restaurant_id,
            table_id=table_id,
            table_session_id=table_session_id,
            status=StaffCallStatus.PENDING,
        )
        session.add(call)

        # 4. Update session.last_activity_at (R13.2)
        await session.execute(
            text("""
                UPDATE table_sessions
                SET last_activity_at = now()
                WHERE id = :session_id
            """),
            {"session_id": table_session_id},
        )

        await session.commit()
        await session.refresh(call)

        # 5. Publish staff_call.new event
        payload = {
            "call": {
                "id": str(call.id),
                "table_id": str(call.table_id),
                "table_session_id": str(call.table_session_id),
                "status": call.status.value,
                "created_at": call.created_at.isoformat(),
            },
        }
        await RealtimePublisher.publish(
            kitchen_channel(restaurant_id),
            EventTypes.STAFF_CALL_NEW,
            payload,
            redis_client,
        )
        await RealtimePublisher.publish(
            session_channel(restaurant_id, table_session_id),
            EventTypes.STAFF_CALL_NEW,
            payload,
            redis_client,
        )

        return call

    @staticmethod
    async def ack(
        call_id: uuid.UUID,
        actor_user_id: uuid.UUID,
        restaurant_id: uuid.UUID,
        session: AsyncSession,
        redis_client: aioredis.Redis,
    ) -> StaffCall:
        """Acknowledge a pending staff call (R7.3).

        Raises:
            ValueError: If the call is not found or doesn't belong to the restaurant.
        """
        # Find the call with tenant isolation
        result = await session.execute(
            select(StaffCall).where(
                StaffCall.id == call_id,
                StaffCall.restaurant_id == restaurant_id,
            )
        )
        call = result.scalar_one_or_none()

        if call is None:
            raise ValueError("Yêu cầu gọi nhân viên không tồn tại.")

        if call.status == StaffCallStatus.ACKNOWLEDGED:
            # Already acknowledged — idempotent return
            return call

        # Update status
        call.status = StaffCallStatus.ACKNOWLEDGED
        call.acknowledged_at = datetime.now(timezone.utc)
        call.acknowledged_by = actor_user_id
        session.add(call)
        await session.commit()
        await session.refresh(call)

        # Publish staff_call.ack event
        payload = {
            "call": {
                "id": str(call.id),
                "table_id": str(call.table_id),
                "table_session_id": str(call.table_session_id),
                "status": call.status.value,
                "acknowledged_at": call.acknowledged_at.isoformat(),
                "acknowledged_by": str(call.acknowledged_by),
            },
        }
        await RealtimePublisher.publish(
            kitchen_channel(restaurant_id),
            EventTypes.STAFF_CALL_ACK,
            payload,
            redis_client,
        )
        await RealtimePublisher.publish(
            session_channel(restaurant_id, call.table_session_id),
            EventTypes.STAFF_CALL_ACK,
            payload,
            redis_client,
        )

        return call

    @staticmethod
    async def dismiss_pending(
        session_id: uuid.UUID,
        restaurant_id: uuid.UUID,
        session: AsyncSession,
    ) -> int:
        """Bulk-dismiss all pending staff calls for a session.

        Sets status='acknowledged' and acknowledged_at=now() for all pending
        calls belonging to the given session. Reused by checkout (10.1) and
        auto-abandon sweep (11.1).

        Returns the number of calls dismissed.
        """
        result = await session.execute(
            text("""
                UPDATE staff_calls
                SET status = 'acknowledged',
                    acknowledged_at = now()
                WHERE table_session_id = :session_id
                  AND restaurant_id = :restaurant_id
                  AND status = 'pending'
            """),
            {"session_id": session_id, "restaurant_id": restaurant_id},
        )
        return result.rowcount


async def _get_cooldown(
    restaurant_id: uuid.UUID,
    session: AsyncSession,
) -> int:
    """Read staff_call_cooldown_seconds from restaurant_settings."""
    result = await session.execute(
        select(RestaurantSettings.staff_call_cooldown_seconds).where(
            RestaurantSettings.restaurant_id == restaurant_id,
        )
    )
    value = result.scalar_one_or_none()
    return value if value is not None else _DEFAULT_COOLDOWN_SECONDS
