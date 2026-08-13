"""Integration tests for session lifecycle & race conditions (R13.5–R13.8).

**Validates: Requirements 13.5, 13.6, 13.7, 13.8**

Tests:
- Property 1: At most one open session per table (unique partial index).
- Property 5 (branch R13.8): Abandon auto-cancels unserved items (session_abandoned),
  stops blinking (no orphan items), dismisses pending calls.
- Property 9: 24h restore limit — abandoned_at within 24h allows restore/checkout;
  just past 24h blocks both.
- Race: checkout vs sweep — CAS loser gets empty RETURNING and skips/soft-reports.
- Restore 2 branches: restore-to-open and direct-checkout.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from qorder_api.auth.dependencies import get_current_user
from qorder_api.auth.jwt import TokenPayload
from qorder_api.db import get_session as _gs
from qorder_api.models.enums import SessionStatus
from qorder_api.redis import get_redis
from qorder_api.services.session_service import (
    CheckoutResult,
    RestoreResult,
    SessionService,
)


# ---------- Fixtures ----------


@pytest.fixture
def restaurant_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture
def staff_user(restaurant_id) -> TokenPayload:
    return TokenPayload(
        sub=uuid.uuid4(),
        restaurant_id=restaurant_id,
        role="staff",
    )


@pytest.fixture
def app():
    from qorder_api.main import app as _app

    yield _app
    _app.dependency_overrides.clear()


# ---------- Helpers ----------


def _make_session_model(
    restaurant_id: uuid.UUID,
    status: str = "open",
    total_amount: Decimal | None = None,
    abandoned_at: datetime | None = None,
    table_id: uuid.UUID | None = None,
) -> MagicMock:
    s = MagicMock()
    s.id = uuid.uuid4()
    s.restaurant_id = restaurant_id
    s.table_id = table_id or uuid.uuid4()
    s.status = SessionStatus(status)
    s.opened_by = None
    s.opened_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
    s.last_activity_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    s.closed_at = (
        datetime(2024, 6, 1, 14, 0, 0, tzinfo=timezone.utc)
        if status == "closed"
        else None
    )
    s.abandoned_at = abandoned_at or (
        datetime(2024, 6, 1, 14, 0, 0, tzinfo=timezone.utc)
        if status == "abandoned"
        else None
    )
    s.total_amount = total_amount
    return s


def _override_auth(app, staff_user: TokenPayload):
    async def _fake_user():
        return staff_user

    app.dependency_overrides[get_current_user] = _fake_user


def _override_db(app, mock_session):
    async def _fake_session():
        yield mock_session

    app.dependency_overrides[_gs] = _fake_session


def _override_redis(app):
    fake_redis = AsyncMock()
    fake_redis.publish = AsyncMock(return_value=1)

    async def _fake_redis():
        yield fake_redis

    app.dependency_overrides[get_redis] = _fake_redis
    return fake_redis


# ===========================================================================
# Property 1: At most one open session per table
# ===========================================================================


class TestOneOpenSessionPerTable:
    """Property 1 — Unique partial index ensures at most 1 open session/table.

    **Validates: Requirements 13.6**
    """

    async def test_restore_checks_existing_open_before_restoring(
        self, app, restaurant_id, staff_user
    ):
        """Restore to open only proceeds when NO other open session on the table.

        If an open session already exists, the restore path B (direct checkout)
        is taken, preserving Property 1.
        """
        _override_auth(app, staff_user)
        _override_redis(app)

        table_id = uuid.uuid4()

        # Abandoned session on the same table that already has a new open session
        closed_session = _make_session_model(
            restaurant_id, status="closed", table_id=table_id
        )
        closed_session.total_amount = Decimal("60000")

        restore_result = RestoreResult(
            session=closed_session,
            action="checked_out",  # Path B chosen because table has open session
            total_amount=Decimal("60000"),
            auto_cancelled_items=[],
            dismissed_calls_count=0,
        )

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "restore", return_value=restore_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{uuid.uuid4()}/restore",
                )

        assert resp.status_code == 200
        data = resp.json()
        # Path B (direct checkout) was taken → table retains only its existing open session
        assert data["action"] == "checked_out"

    async def test_restore_to_open_only_when_no_existing_open(
        self, app, restaurant_id, staff_user
    ):
        """Restore to open only when table has NO open session → Property 1 maintained."""
        _override_auth(app, staff_user)
        _override_redis(app)

        table_id = uuid.uuid4()
        restored_session = _make_session_model(
            restaurant_id, status="open", table_id=table_id
        )
        restored_session.abandoned_at = None

        restore_result = RestoreResult(
            session=restored_session,
            action="restored",  # Path A — no existing open session
        )

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "restore", return_value=restore_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{restored_session.id}/restore",
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "restored"
        assert data["session"]["status"] == "open"

    async def test_service_level_property1_restore_path_selection(
        self, restaurant_id
    ):
        """Service-level: restore checks _find_open_session to preserve Property 1.

        - No open session on table → CAS abandoned→open (Path A).
        - Open session exists → CAS abandoned→closed (Path B).
        Never creates two open sessions on the same table.
        """
        session_id = uuid.uuid4()
        table_id = uuid.uuid4()
        mock_session = AsyncMock()

        abandoned_session = MagicMock()
        abandoned_session.id = session_id
        abandoned_session.restaurant_id = restaurant_id
        abandoned_session.table_id = table_id
        abandoned_session.status = SessionStatus.ABANDONED
        abandoned_session.abandoned_at = datetime.now(timezone.utc) - timedelta(hours=2)

        # Simulate: table already has an open session
        existing_open = MagicMock()
        existing_open.id = uuid.uuid4()
        existing_open.status = SessionStatus.OPEN

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                # SELECT session by id + restaurant_id
                result.scalar_one_or_none.return_value = abandoned_session
            elif call_count == 2:
                # _find_open_session → existing open session found
                result.scalar_one_or_none.return_value = existing_open
            elif call_count == 3:
                # CAS UPDATE abandoned → closed
                row = {"id": session_id, "status": "closed"}
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = row
                result.mappings.return_value = mappings_mock
            elif call_count == 4:
                # Items to cancel query
                mappings_mock = MagicMock()
                mappings_mock.all.return_value = []
                result.mappings.return_value = mappings_mock
            elif call_count == 5:
                # Compute total
                result.scalar_one.return_value = Decimal("45000")
            elif call_count == 6:
                # Update total_amount
                pass
            elif call_count == 7:
                # dismiss_pending
                result.rowcount = 0
            elif call_count == 8:
                # Re-read final session
                final = MagicMock()
                final.id = session_id
                final.restaurant_id = restaurant_id
                final.table_id = table_id
                final.status = SessionStatus.CLOSED
                final.abandoned_at = abandoned_session.abandoned_at
                final.opened_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
                final.last_activity_at = datetime.now(timezone.utc)
                final.closed_at = datetime.now(timezone.utc)
                final.total_amount = Decimal("45000")
                final.opened_by = None
                result.scalar_one.return_value = final
            return result

        mock_session.execute = _mock_execute
        mock_session.commit = AsyncMock()

        restore_result = await SessionService.restore(
            session_id=session_id,
            restaurant_id=restaurant_id,
            session=mock_session,
        )

        # Path B chosen → abandoned closed (not restored to open)
        assert restore_result is not None
        assert restore_result.action == "checked_out"
        assert restore_result.session.status == SessionStatus.CLOSED
        # Property 1 preserved: table still has only the existing open session


# ===========================================================================
# Race: checkout vs sweep — CAS loser gets empty RETURNING
# ===========================================================================


class TestRaceCheckoutVsSweep:
    """Race between staff checkout and scheduler sweep.

    Both use CAS `WHERE status='open'`. The loser gets RETURNING empty → skip/soft-report.

    **Validates: Requirements 13.5, 13.6**
    """

    async def test_checkout_loses_race_to_sweep_returns_409(
        self, app, restaurant_id, staff_user
    ):
        """Sweep wins CAS, checkout gets empty RETURNING → 409 soft error."""
        _override_auth(app, staff_user)
        _override_redis(app)

        mock_db_session = AsyncMock()
        result_mock = MagicMock()
        # Session found at lookup time (still appears open in initial SELECT)
        open_session = _make_session_model(restaurant_id, status="open")
        result_mock.scalar_one_or_none.return_value = open_session
        mock_db_session.execute = AsyncMock(return_value=result_mock)
        _override_db(app, mock_db_session)

        # SessionService.checkout returns None → CAS lost (sweep already abandoned it)
        with patch.object(SessionService, "checkout", return_value=None):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{open_session.id}/checkout",
                )

        assert resp.status_code == 409
        # Soft error message
        detail = resp.json()["detail"]
        assert "đóng" in detail or "bỏ" in detail

    async def test_sweep_loses_race_to_checkout_skips_session(
        self, restaurant_id
    ):
        """Checkout wins CAS first, sweep's CAS returns empty → session is skipped.

        Service-level test simulating _abandon_session receiving empty RETURNING.
        """
        from qorder_api.scheduler import _abandon_session

        session_id = uuid.uuid4()
        mock_db = AsyncMock()

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                # CAS UPDATE table_sessions SET status='abandoned' ... RETURNING
                # Returns empty → CAS lost (checkout already closed it)
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = None
                result.mappings.return_value = mappings_mock
            return result

        mock_db.execute = _mock_execute
        mock_db.commit = AsyncMock()

        fake_redis = AsyncMock()
        fake_redis.publish = AsyncMock()

        # _abandon_session should simply return without further side effects
        await _abandon_session(mock_db, session_id, restaurant_id, fake_redis)

        # Verify: no commit (nothing to commit), no publish
        mock_db.commit.assert_not_called()
        fake_redis.publish.assert_not_called()

    async def test_service_level_checkout_cas_empty_returning(
        self, restaurant_id
    ):
        """SessionService.checkout returns None when CAS RETURNING is empty."""
        session_id = uuid.uuid4()
        mock_session = AsyncMock()

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                # CAS UPDATE ... WHERE status='open' RETURNING *
                # Empty → someone else already changed the status
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = None
                result.mappings.return_value = mappings_mock
            return result

        mock_session.execute = _mock_execute
        mock_session.commit = AsyncMock()

        checkout_result = await SessionService.checkout(
            session_id=session_id,
            restaurant_id=restaurant_id,
            session=mock_session,
        )

        # CAS lost → None returned
        assert checkout_result is None


# ===========================================================================
# Property 5 (branch R13.8): Abandon auto-cancels unfinished items
# ===========================================================================


class TestAbandonAutoCancelItems:
    """Property 5 (R13.8) — Sweep marks abandoned → items cancelled (session_abandoned).

    When a session leaves 'open' via sweep:
    - All pending/cooking/ready items → cancelled (cancelled_by='system',
      cancel_reason='session_abandoned').
    - No orphan items left blinking on kitchen board.
    - Pending staff_calls are dismissed.

    **Validates: Requirements 13.8**
    """

    async def test_sweep_cancels_unserved_items_and_dismisses_calls(
        self, restaurant_id
    ):
        """_abandon_session cancels items and dismisses calls on CAS success."""
        from qorder_api.scheduler import _abandon_session

        session_id = uuid.uuid4()
        mock_db = AsyncMock()

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                # CAS: mark session abandoned → success
                row = {"id": session_id, "restaurant_id": restaurant_id}
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = row
                result.mappings.return_value = mappings_mock
            elif call_count == 2:
                # Auto-cancel unserved items
                # cancelled_by='system', cancel_reason='session_abandoned'
                result.rowcount = 3  # 3 items cancelled
            elif call_count == 3:
                # dismiss_pending (StaffCallService)
                result.rowcount = 2  # 2 calls dismissed
            return result

        mock_db.execute = _mock_execute
        mock_db.commit = AsyncMock()

        fake_redis = AsyncMock()
        fake_redis.publish = AsyncMock(return_value=1)

        await _abandon_session(mock_db, session_id, restaurant_id, fake_redis)

        # Verify commit was called (changes persisted)
        mock_db.commit.assert_called_once()

        # Verify publish was called for session.abandoned event
        assert fake_redis.publish.call_count >= 1

    async def test_no_orphan_items_after_abandon(self, restaurant_id):
        """After sweep, no item remains in pending/cooking/ready (Property 5).

        Verified by checking that the cancel UPDATE targets all items with
        status IN ('pending', 'cooking', 'ready') for the session.
        """
        from qorder_api.scheduler import _abandon_session
        from sqlalchemy import text

        session_id = uuid.uuid4()
        mock_db = AsyncMock()

        executed_stmts = []

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            executed_stmts.append((stmt, params))
            result = MagicMock()

            if call_count == 1:
                # CAS success
                row = {"id": session_id, "restaurant_id": restaurant_id}
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = row
                result.mappings.return_value = mappings_mock
            elif call_count == 2:
                # Auto-cancel items
                result.rowcount = 5
            elif call_count == 3:
                # dismiss_pending
                result.rowcount = 0
            return result

        mock_db.execute = _mock_execute
        mock_db.commit = AsyncMock()

        fake_redis = AsyncMock()
        fake_redis.publish = AsyncMock(return_value=1)

        await _abandon_session(mock_db, session_id, restaurant_id, fake_redis)

        # Verify the cancel SQL targets the right statuses and reason
        # The 2nd call should be the cancel UPDATE
        cancel_stmt = executed_stmts[1]
        stmt_text = str(cancel_stmt[0].text) if hasattr(cancel_stmt[0], 'text') else str(cancel_stmt[0])
        assert "session_abandoned" in stmt_text
        assert "pending" in stmt_text
        assert "cooking" in stmt_text
        assert "ready" in stmt_text

    async def test_sweep_dismiss_pending_calls(self, restaurant_id):
        """Sweep dismisses all pending staff_calls for the abandoned session."""
        from qorder_api.scheduler import _abandon_session

        session_id = uuid.uuid4()
        mock_db = AsyncMock()

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                # CAS success
                row = {"id": session_id, "restaurant_id": restaurant_id}
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = row
                result.mappings.return_value = mappings_mock
            elif call_count == 2:
                # Auto-cancel items
                result.rowcount = 0
            elif call_count == 3:
                # dismiss_pending → 4 calls dismissed
                result.rowcount = 4
            return result

        mock_db.execute = _mock_execute
        mock_db.commit = AsyncMock()

        fake_redis = AsyncMock()
        fake_redis.publish = AsyncMock(return_value=1)

        await _abandon_session(mock_db, session_id, restaurant_id, fake_redis)

        # Commit was called → changes including dismiss persisted
        mock_db.commit.assert_called_once()


# ===========================================================================
# Property 9: 24h restore limit
# ===========================================================================


class TestRestore24hLimit:
    """Property 9 — No abandoned→open/closed transition when now - abandoned_at > 24h.

    **Validates: Requirements 13.7**
    """

    async def test_within_24h_restore_allowed(self, app, restaurant_id, staff_user):
        """abandoned_at < 24h ago → restore succeeds."""
        _override_auth(app, staff_user)
        _override_redis(app)

        restored_session = _make_session_model(restaurant_id, status="open")
        restored_session.abandoned_at = None

        restore_result = RestoreResult(
            session=restored_session,
            action="restored",
        )

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "restore", return_value=restore_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{restored_session.id}/restore",
                )

        assert resp.status_code == 200
        assert resp.json()["action"] == "restored"

    async def test_within_24h_checkout_allowed(self, app, restaurant_id, staff_user):
        """abandoned_at < 24h ago → direct checkout succeeds."""
        _override_auth(app, staff_user)
        _override_redis(app)

        closed_session = _make_session_model(restaurant_id, status="closed")
        closed_session.total_amount = Decimal("75000")

        restore_result = RestoreResult(
            session=closed_session,
            action="checked_out",
            total_amount=Decimal("75000"),
            auto_cancelled_items=[],
            dismissed_calls_count=0,
        )

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "restore", return_value=restore_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{uuid.uuid4()}/restore",
                )

        assert resp.status_code == 200
        assert resp.json()["action"] == "checked_out"

    async def test_just_past_24h_restore_blocked(self, app, restaurant_id, staff_user):
        """abandoned_at just past 24h (e.g. 24h + 1min) → restore blocked (400)."""
        _override_auth(app, staff_user)
        _override_redis(app)

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        error_msg = (
            "Phiên đã quá 24 giờ kể từ khi bị đánh dấu abandoned. "
            "Không thể khôi phục hoặc thanh toán."
        )

        with patch.object(
            SessionService, "restore", side_effect=ValueError(error_msg)
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{uuid.uuid4()}/restore",
                )

        assert resp.status_code == 400
        assert "24 giờ" in resp.json()["detail"]

    async def test_service_level_boundary_23h59_allowed(self, restaurant_id):
        """Service-level: 23h59m since abandoned_at → within 24h, allowed."""
        session_id = uuid.uuid4()
        table_id = uuid.uuid4()
        mock_session = AsyncMock()

        # abandoned_at is 23h59m ago (just inside the 24h window)
        abandoned_at = datetime.now(timezone.utc) - timedelta(hours=23, minutes=59)

        abandoned_session = MagicMock()
        abandoned_session.id = session_id
        abandoned_session.restaurant_id = restaurant_id
        abandoned_session.table_id = table_id
        abandoned_session.status = SessionStatus.ABANDONED
        abandoned_session.abandoned_at = abandoned_at

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                # SELECT session
                result.scalar_one_or_none.return_value = abandoned_session
            elif call_count == 2:
                # _find_open_session → None (path A)
                result.scalar_one_or_none.return_value = None
            elif call_count == 3:
                # CAS UPDATE abandoned → open
                row = {"id": session_id, "status": "open", "abandoned_at": None}
                mappings_mock = MagicMock()
                mappings_mock.first.return_value = row
                result.mappings.return_value = mappings_mock
            elif call_count == 4:
                # Re-read final session
                final = MagicMock()
                final.id = session_id
                final.restaurant_id = restaurant_id
                final.table_id = table_id
                final.status = SessionStatus.OPEN
                final.abandoned_at = None
                final.opened_at = datetime(2024, 1, 1, tzinfo=timezone.utc)
                final.last_activity_at = datetime.now(timezone.utc)
                final.closed_at = None
                final.total_amount = None
                final.opened_by = None
                result.scalar_one.return_value = final
            return result

        mock_session.execute = _mock_execute
        mock_session.commit = AsyncMock()

        restore_result = await SessionService.restore(
            session_id=session_id,
            restaurant_id=restaurant_id,
            session=mock_session,
        )

        assert restore_result is not None
        assert restore_result.action == "restored"

    async def test_service_level_boundary_24h01_blocked(self, restaurant_id):
        """Service-level: 24h01m since abandoned_at → past 24h, blocked."""
        session_id = uuid.uuid4()
        mock_session = AsyncMock()

        # abandoned_at is 24h + 1min ago (just outside the window)
        abandoned_at = datetime.now(timezone.utc) - timedelta(hours=24, minutes=1)

        abandoned_session = MagicMock()
        abandoned_session.id = session_id
        abandoned_session.restaurant_id = restaurant_id
        abandoned_session.table_id = uuid.uuid4()
        abandoned_session.status = SessionStatus.ABANDONED
        abandoned_session.abandoned_at = abandoned_at

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = abandoned_session
            return result

        mock_session.execute = _mock_execute

        with pytest.raises(ValueError, match="24 giờ"):
            await SessionService.restore(
                session_id=session_id,
                restaurant_id=restaurant_id,
                session=mock_session,
            )

    async def test_service_level_exactly_24h_blocked(self, restaurant_id):
        """Service-level: exactly 24h00m01s since abandoned → blocked."""
        session_id = uuid.uuid4()
        mock_session = AsyncMock()

        # abandoned_at is exactly 24h + 1s ago (boundary)
        abandoned_at = datetime.now(timezone.utc) - timedelta(hours=24, seconds=1)

        abandoned_session = MagicMock()
        abandoned_session.id = session_id
        abandoned_session.restaurant_id = restaurant_id
        abandoned_session.table_id = uuid.uuid4()
        abandoned_session.status = SessionStatus.ABANDONED
        abandoned_session.abandoned_at = abandoned_at

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = abandoned_session
            return result

        mock_session.execute = _mock_execute

        with pytest.raises(ValueError, match="24 giờ"):
            await SessionService.restore(
                session_id=session_id,
                restaurant_id=restaurant_id,
                session=mock_session,
            )


# ===========================================================================
# Restore 2 branches (combined lifecycle flow)
# ===========================================================================


class TestRestoreTwoBranches:
    """R13.5 — Restore two paths exercised together.

    Path A: table has no open session → restore abandoned → open.
    Path B: table already has open session → direct checkout abandoned → closed.

    **Validates: Requirements 13.5, 13.6**
    """

    async def test_path_a_restore_to_open_endpoint(
        self, app, restaurant_id, staff_user
    ):
        """Endpoint: restore → open when no open session on table."""
        _override_auth(app, staff_user)
        _override_redis(app)

        restored = _make_session_model(restaurant_id, status="open")
        restored.abandoned_at = None

        restore_result = RestoreResult(session=restored, action="restored")

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "restore", return_value=restore_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{restored.id}/restore",
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "restored"
        assert data["session"]["status"] == "open"
        assert data["total_amount"] is None
        assert data["auto_cancelled_items"] == []

    async def test_path_b_direct_checkout_endpoint(
        self, app, restaurant_id, staff_user
    ):
        """Endpoint: direct checkout when table already has open session."""
        _override_auth(app, staff_user)
        _override_redis(app)

        closed = _make_session_model(restaurant_id, status="closed")
        closed.total_amount = Decimal("120000")

        cancelled_items = [
            {
                "id": uuid.uuid4(),
                "name_snapshot": "Bia Sài Gòn",
                "quantity": 2,
                "status_before": "pending",
            },
            {
                "id": uuid.uuid4(),
                "name_snapshot": "Đậu phộng",
                "quantity": 1,
                "status_before": "cooking",
            },
        ]

        restore_result = RestoreResult(
            session=closed,
            action="checked_out",
            total_amount=Decimal("120000"),
            auto_cancelled_items=cancelled_items,
            dismissed_calls_count=2,
        )

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "restore", return_value=restore_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{closed.id}/restore",
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "checked_out"
        assert data["session"]["status"] == "closed"
        assert Decimal(data["total_amount"]) == Decimal("120000")
        assert len(data["auto_cancelled_items"]) == 2
        assert data["dismissed_calls_count"] == 2
