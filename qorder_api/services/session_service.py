"""Session lifecycle service (R2.4, R6.1, R6.2, R13.6).

Provides:
- ``get_or_open``: Returns existing open session or creates one (R2.4, R13.6).
- ``checkout``: CAS-based checkout with auto-cancel and total calculation (R6.1, R6.2).

Uses the unique partial index ``uq_one_open_session_per_table``
(``table_id WHERE status='open'``) to prevent race conditions on open.
Checkout uses CAS (``WHERE status='open'``) to prevent double-close.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from qorder_api.models.enums import SessionStatus
from qorder_api.models.session import TableSession


@dataclass
class CheckoutResult:
    """Result of a successful checkout operation."""

    session: TableSession
    total_amount: Decimal
    auto_cancelled_items: list[dict] = field(default_factory=list)
    """Each dict has: id, name_snapshot, quantity, status_before."""
    dismissed_calls_count: int = 0


@dataclass
class RestoreResult:
    """Result of a successful restore operation (R13.5).

    ``action`` indicates which path was taken:
    - ``"restored"`` → session moved back to ``open``.
    - ``"checked_out"`` → session moved directly to ``closed`` (direct checkout).
    """

    session: TableSession
    action: str
    """Either 'restored' or 'checked_out'."""
    total_amount: Decimal | None = None
    """Only set when action='checked_out'."""
    auto_cancelled_items: list[dict] = field(default_factory=list)
    """Only populated when action='checked_out'."""
    dismissed_calls_count: int = 0


class SessionService:
    """Manages table session lifecycle."""

    @staticmethod
    async def get_or_open(
        table_id: uuid.UUID,
        restaurant_id: uuid.UUID,
        session: AsyncSession,
        opened_by: uuid.UUID | None = None,
    ) -> TableSession:
        """Get the current open session for a table, or create one.

        Uses the unique partial index on (table_id WHERE status='open') to
        prevent races. If two concurrent requests try to create a session,
        one will get IntegrityError (UniqueViolation). The loser catches the
        error and reads back the existing open session.

        Args:
            table_id: The table to open a session for.
            restaurant_id: Tenant scope.
            session: SQLAlchemy async session.
            opened_by: User UUID if staff manually opened; None for customer QR.

        Returns:
            The open TableSession (existing or newly created).
        """
        # 1. Try to find existing open session
        existing = await _find_open_session(table_id, session)
        if existing is not None:
            return existing

        # 2. No open session found — try to create one
        new_session = TableSession(
            restaurant_id=restaurant_id,
            table_id=table_id,
            status=SessionStatus.OPEN,
            opened_by=opened_by,
        )
        session.add(new_session)

        try:
            await session.flush()
        except IntegrityError:
            # Another request won the race and created a session first.
            # Rollback the failed INSERT and read back the winner.
            await session.rollback()
            existing = await _find_open_session(table_id, session)
            if existing is not None:
                return existing
            # Extremely unlikely: the winning session was closed between
            # our flush failure and re-read. Raise to signal unexpected state.
            raise RuntimeError(
                f"Race recovery failed: no open session found for table {table_id}"
            )

        await session.commit()
        await session.refresh(new_session)
        return new_session

    @staticmethod
    async def checkout(
        session_id: uuid.UUID,
        restaurant_id: uuid.UUID,
        session: AsyncSession,
    ) -> CheckoutResult | None:
        """Close a session via CAS, auto-cancel unserved items, compute total.

        Uses compare-and-swap: ``UPDATE ... WHERE status='open' RETURNING *``.
        If RETURNING is empty → session was already closed/abandoned by another
        actor (e.g., auto-abandon sweep). Returns None to signal soft failure.

        Steps:
            1. CAS close the session.
            2. Fetch items that will be auto-cancelled (for warning response).
            3. Auto-cancel all non-served/non-cancelled items.
            4. Compute total_amount from served items only.
            5. Update session.total_amount.
            6. Dismiss pending staff calls via StaffCallService.
            7. Commit and return CheckoutResult.

        Args:
            session_id: The table_session to check out.
            restaurant_id: Tenant scope.
            session: SQLAlchemy async session.

        Returns:
            CheckoutResult on success, None if CAS lost (session not open).
        """
        from qorder_api.services.staff_call_service import StaffCallService

        # 1. CAS: close session only if it's currently open
        cas_result = await session.execute(
            text("""
                UPDATE table_sessions
                SET status = 'closed',
                    closed_at = now()
                WHERE id = :session_id
                  AND restaurant_id = :restaurant_id
                  AND status = 'open'
                RETURNING *
            """),
            {"session_id": session_id, "restaurant_id": restaurant_id},
        )
        closed_row = cas_result.mappings().first()

        if closed_row is None:
            # CAS lost: session was already closed or abandoned
            return None

        # 2. Find items that will be auto-cancelled (for the warning response)
        items_to_cancel_result = await session.execute(
            text("""
                SELECT id, name_snapshot, quantity, status
                FROM order_items
                WHERE order_id IN (
                    SELECT id FROM orders WHERE table_session_id = :session_id
                )
                AND status IN ('pending', 'cooking', 'ready')
            """),
            {"session_id": session_id},
        )
        items_to_cancel = items_to_cancel_result.mappings().all()

        auto_cancelled: list[dict] = [
            {
                "id": row["id"],
                "name_snapshot": row["name_snapshot"],
                "quantity": row["quantity"],
                "status_before": row["status"],
            }
            for row in items_to_cancel
        ]

        # 3. Auto-cancel all unserved items (R6.6, R6.8)
        if auto_cancelled:
            await session.execute(
                text("""
                    UPDATE order_items
                    SET status = 'cancelled',
                        cancelled_by = 'system',
                        cancelled_at = now(),
                        cancel_reason = 'table_closed'
                    WHERE order_id IN (
                        SELECT id FROM orders WHERE table_session_id = :session_id
                    )
                    AND status IN ('pending', 'cooking', 'ready')
                """),
                {"session_id": session_id},
            )

        # 4. Compute total_amount from served items only (R6.1, Property 3)
        total_result = await session.execute(
            text("""
                SELECT COALESCE(SUM(price_snapshot * quantity), 0) AS total
                FROM order_items
                WHERE order_id IN (
                    SELECT id FROM orders WHERE table_session_id = :session_id
                )
                AND status = 'served'
            """),
            {"session_id": session_id},
        )
        total_amount = Decimal(str(total_result.scalar_one()))

        # 5. Update session.total_amount
        await session.execute(
            text("""
                UPDATE table_sessions
                SET total_amount = :total_amount
                WHERE id = :session_id
            """),
            {"total_amount": total_amount, "session_id": session_id},
        )

        # 6. Dismiss pending staff calls (R6.9) — reuse existing service
        dismissed_count = await StaffCallService.dismiss_pending(
            session_id=session_id,
            restaurant_id=restaurant_id,
            session=session,
        )

        # 7. Commit all changes
        await session.commit()

        # 8. Re-read the final session state
        final_result = await session.execute(
            select(TableSession).where(TableSession.id == session_id)
        )
        final_session = final_result.scalar_one()

        return CheckoutResult(
            session=final_session,
            total_amount=total_amount,
            auto_cancelled_items=auto_cancelled,
            dismissed_calls_count=dismissed_count,
        )


    @staticmethod
    async def restore(
        session_id: uuid.UUID,
        restaurant_id: uuid.UUID,
        session: AsyncSession,
    ) -> RestoreResult | None:
        """Restore an abandoned session (R13.5, R13.6, R13.7).

        Two paths:
        1. Table has NO other open session → restore abandoned → open.
        2. Table ALREADY has an open session → direct checkout abandoned → closed.

        Returns None if:
        - Session not found / not abandoned / not owned by restaurant.
        - Abandoned for more than 24 hours (R13.7).

        Raises:
            ValueError: With a descriptive message for known business errors.
        """
        from qorder_api.services.staff_call_service import StaffCallService

        # 1. Fetch session and verify it's abandoned + belongs to restaurant
        result = await session.execute(
            select(TableSession).where(
                TableSession.id == session_id,
                TableSession.restaurant_id == restaurant_id,
            )
        )
        table_session = result.scalar_one_or_none()

        if table_session is None:
            return None

        if table_session.status != SessionStatus.ABANDONED:
            raise ValueError("Chỉ có thể khôi phục phiên ở trạng thái 'abandoned'.")

        # 2. Check 24h limit (R13.7)
        if table_session.abandoned_at is None:
            raise ValueError("Phiên thiếu thời điểm abandoned_at.")

        from datetime import datetime, timezone, timedelta

        now = datetime.now(timezone.utc)
        # Ensure abandoned_at is timezone-aware for comparison
        abandoned_at = table_session.abandoned_at
        if abandoned_at.tzinfo is None:
            abandoned_at = abandoned_at.replace(tzinfo=timezone.utc)

        if (now - abandoned_at) > timedelta(hours=24):
            raise ValueError(
                "Phiên đã quá 24 giờ kể từ khi bị đánh dấu abandoned. "
                "Không thể khôi phục hoặc thanh toán."
            )

        # 3. Check if table already has an open session
        existing_open = await _find_open_session(table_session.table_id, session)

        if existing_open is None:
            # Path A: No open session on table → restore to open
            cas_result = await session.execute(
                text("""
                    UPDATE table_sessions
                    SET status = 'open',
                        abandoned_at = NULL,
                        last_activity_at = now()
                    WHERE id = :session_id
                      AND restaurant_id = :restaurant_id
                      AND status = 'abandoned'
                    RETURNING *
                """),
                {"session_id": session_id, "restaurant_id": restaurant_id},
            )
            restored_row = cas_result.mappings().first()

            if restored_row is None:
                # CAS lost — someone else changed the session
                raise ValueError(
                    "Không thể khôi phục: phiên vừa bị thay đổi bởi thao tác khác."
                )

            await session.commit()

            # Re-read final state
            final_result = await session.execute(
                select(TableSession).where(TableSession.id == session_id)
            )
            final_session = final_result.scalar_one()

            return RestoreResult(
                session=final_session,
                action="restored",
            )
        else:
            # Path B: Table already has an open session → direct checkout
            # (abandoned → closed) with total from served items only

            # CAS: close the abandoned session
            cas_result = await session.execute(
                text("""
                    UPDATE table_sessions
                    SET status = 'closed',
                        closed_at = now()
                    WHERE id = :session_id
                      AND restaurant_id = :restaurant_id
                      AND status = 'abandoned'
                    RETURNING *
                """),
                {"session_id": session_id, "restaurant_id": restaurant_id},
            )
            closed_row = cas_result.mappings().first()

            if closed_row is None:
                raise ValueError(
                    "Không thể thanh toán: phiên vừa bị thay đổi bởi thao tác khác."
                )

            # Auto-cancel unserved items (like normal checkout)
            items_to_cancel_result = await session.execute(
                text("""
                    SELECT id, name_snapshot, quantity, status
                    FROM order_items
                    WHERE order_id IN (
                        SELECT id FROM orders WHERE table_session_id = :session_id
                    )
                    AND status IN ('pending', 'cooking', 'ready')
                """),
                {"session_id": session_id},
            )
            items_to_cancel = items_to_cancel_result.mappings().all()

            auto_cancelled: list[dict] = [
                {
                    "id": row["id"],
                    "name_snapshot": row["name_snapshot"],
                    "quantity": row["quantity"],
                    "status_before": row["status"],
                }
                for row in items_to_cancel
            ]

            if auto_cancelled:
                await session.execute(
                    text("""
                        UPDATE order_items
                        SET status = 'cancelled',
                            cancelled_by = 'system',
                            cancelled_at = now(),
                            cancel_reason = 'table_closed'
                        WHERE order_id IN (
                            SELECT id FROM orders WHERE table_session_id = :session_id
                        )
                        AND status IN ('pending', 'cooking', 'ready')
                    """),
                    {"session_id": session_id},
                )

            # Compute total from served items only
            total_result = await session.execute(
                text("""
                    SELECT COALESCE(SUM(price_snapshot * quantity), 0) AS total
                    FROM order_items
                    WHERE order_id IN (
                        SELECT id FROM orders WHERE table_session_id = :session_id
                    )
                    AND status = 'served'
                """),
                {"session_id": session_id},
            )
            total_amount = Decimal(str(total_result.scalar_one()))

            # Update total_amount
            await session.execute(
                text("""
                    UPDATE table_sessions
                    SET total_amount = :total_amount
                    WHERE id = :session_id
                """),
                {"total_amount": total_amount, "session_id": session_id},
            )

            # Dismiss pending staff calls
            dismissed_count = await StaffCallService.dismiss_pending(
                session_id=session_id,
                restaurant_id=restaurant_id,
                session=session,
            )

            await session.commit()

            # Re-read final state
            final_result = await session.execute(
                select(TableSession).where(TableSession.id == session_id)
            )
            final_session = final_result.scalar_one()

            return RestoreResult(
                session=final_session,
                action="checked_out",
                total_amount=total_amount,
                auto_cancelled_items=auto_cancelled,
                dismissed_calls_count=dismissed_count,
            )


async def _find_open_session(
    table_id: uuid.UUID,
    session: AsyncSession,
) -> TableSession | None:
    """Find the open session for a table, or None."""
    result = await session.execute(
        select(TableSession).where(
            TableSession.table_id == table_id,
            TableSession.status == SessionStatus.OPEN,
        )
    )
    return result.scalar_one_or_none()
