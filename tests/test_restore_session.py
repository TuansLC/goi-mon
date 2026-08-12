"""Integration tests for session restore flow (R13.5, R13.6, R13.7).

Validates:
- R13.5: Two paths — restore to open (no open session) or direct checkout (has open).
- R13.6: At most 1 open session per table (enforced by restore logic).
- R13.7: 24h limit — block restore/checkout if abandoned > 24h ago.
- Property 9: No abandoned → open/closed transition accepted when now - abandoned_at > 24h.
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
from qorder_api.services.session_service import RestoreResult, SessionService


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
    status: str = "abandoned",
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


# ---------- Tests ----------


class TestRestoreToOpen:
    """R13.5 — Path A: table has no open session → restore abandoned to open."""

    async def test_restore_abandoned_to_open(self, app, restaurant_id, staff_user):
        """When table has no other open session, abandoned session restores to open."""
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
        data = resp.json()
        assert data["action"] == "restored"
        assert data["session"]["status"] == "open"
        assert data["total_amount"] is None
        assert data["auto_cancelled_items"] == []
        assert data["dismissed_calls_count"] == 0


class TestDirectCheckout:
    """R13.5 — Path B: table already has open session → direct checkout."""

    async def test_direct_checkout_when_table_has_open_session(
        self, app, restaurant_id, staff_user
    ):
        """When table already has an open session, abandoned session gets checked out."""
        _override_auth(app, staff_user)
        _override_redis(app)

        closed_session = _make_session_model(restaurant_id, status="closed")
        closed_session.total_amount = Decimal("80000")

        restore_result = RestoreResult(
            session=closed_session,
            action="checked_out",
            total_amount=Decimal("80000"),
            auto_cancelled_items=[
                {
                    "id": uuid.uuid4(),
                    "name_snapshot": "Gỏi cuốn",
                    "quantity": 1,
                    "status_before": "pending",
                },
            ],
            dismissed_calls_count=1,
        )

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "restore", return_value=restore_result):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{closed_session.id}/restore",
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["action"] == "checked_out"
        assert data["session"]["status"] == "closed"
        assert Decimal(data["total_amount"]) == Decimal("80000")
        assert len(data["auto_cancelled_items"]) == 1
        assert data["dismissed_calls_count"] == 1


class TestRestore24hBlock:
    """R13.7 / Property 9 — 24h limit blocks restore/checkout."""

    async def test_block_restore_after_24h(self, app, restaurant_id, staff_user):
        """Restore is blocked when abandoned_at is more than 24h ago."""
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

    async def test_within_24h_allowed(self, app, restaurant_id, staff_user):
        """Restore works within 24h of abandoned_at."""
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


class TestRestoreNotAbandonedSession:
    """Edge case — only abandoned sessions can be restored."""

    async def test_restore_open_session_returns_400(
        self, app, restaurant_id, staff_user
    ):
        """Cannot restore a session that is 'open' (not abandoned)."""
        _override_auth(app, staff_user)
        _override_redis(app)

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        error_msg = "Chỉ có thể khôi phục phiên ở trạng thái 'abandoned'."

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
        assert "abandoned" in resp.json()["detail"]

    async def test_restore_closed_session_returns_400(
        self, app, restaurant_id, staff_user
    ):
        """Cannot restore a session that is 'closed'."""
        _override_auth(app, staff_user)
        _override_redis(app)

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        error_msg = "Chỉ có thể khôi phục phiên ở trạng thái 'abandoned'."

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
        assert "abandoned" in resp.json()["detail"]


class TestRestoreSessionNotFound:
    """Session not found or wrong restaurant → 404."""

    async def test_session_not_found_returns_404(
        self, app, restaurant_id, staff_user
    ):
        """Restore on a non-existent session returns 404."""
        _override_auth(app, staff_user)
        _override_redis(app)

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        with patch.object(SessionService, "restore", return_value=None):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{uuid.uuid4()}/restore",
                )

        assert resp.status_code == 404

    async def test_session_wrong_restaurant_returns_404(
        self, app, restaurant_id, staff_user
    ):
        """Restore on session belonging to another restaurant returns 404."""
        _override_auth(app, staff_user)
        _override_redis(app)

        mock_db_session = AsyncMock()
        _override_db(app, mock_db_session)

        # Service returns None when restaurant_id doesn't match
        with patch.object(SessionService, "restore", return_value=None):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app),
                base_url="http://test",
            ) as ac:
                resp = await ac.post(
                    f"/tables/sessions/{uuid.uuid4()}/restore",
                )

        assert resp.status_code == 404


class TestRestoreServiceUnit:
    """Unit tests for SessionService.restore logic."""

    async def test_restore_to_open_cas(self, restaurant_id):
        """Service-level: CAS transitions abandoned → open when no other open session."""
        session_id = uuid.uuid4()
        table_id = uuid.uuid4()
        mock_session = AsyncMock()

        abandoned_session = MagicMock()
        abandoned_session.id = session_id
        abandoned_session.restaurant_id = restaurant_id
        abandoned_session.table_id = table_id
        abandoned_session.status = SessionStatus.ABANDONED
        abandoned_session.abandoned_at = datetime.now(timezone.utc) - timedelta(hours=2)

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()

            if call_count == 1:
                # SELECT session by id + restaurant_id
                result.scalar_one_or_none.return_value = abandoned_session
            elif call_count == 2:
                # _find_open_session → no open session for table
                result.scalar_one_or_none.return_value = None
            elif call_count == 3:
                # CAS UPDATE abandoned → open
                row = {
                    "id": session_id,
                    "status": "open",
                    "abandoned_at": None,
                }
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
        assert restore_result.session.status == SessionStatus.OPEN
        assert restore_result.total_amount is None

    async def test_direct_checkout_cas(self, restaurant_id):
        """Service-level: CAS transitions abandoned → closed when table has open session."""
        session_id = uuid.uuid4()
        table_id = uuid.uuid4()
        mock_session = AsyncMock()

        abandoned_session = MagicMock()
        abandoned_session.id = session_id
        abandoned_session.restaurant_id = restaurant_id
        abandoned_session.table_id = table_id
        abandoned_session.status = SessionStatus.ABANDONED
        abandoned_session.abandoned_at = datetime.now(timezone.utc) - timedelta(hours=1)

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
                # _find_open_session → found existing open session
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
                result.scalar_one.return_value = Decimal("50000")
            elif call_count == 6:
                # Update total_amount
                pass
            elif call_count == 7:
                # dismiss_pending (StaffCallService)
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
                final.total_amount = Decimal("50000")
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
        assert restore_result.action == "checked_out"
        assert restore_result.total_amount == Decimal("50000")
        assert restore_result.session.status == SessionStatus.CLOSED

    async def test_24h_block(self, restaurant_id):
        """Service-level: restore is rejected when abandoned > 24h ago."""
        session_id = uuid.uuid4()
        mock_session = AsyncMock()

        abandoned_session = MagicMock()
        abandoned_session.id = session_id
        abandoned_session.restaurant_id = restaurant_id
        abandoned_session.table_id = uuid.uuid4()
        abandoned_session.status = SessionStatus.ABANDONED
        abandoned_session.abandoned_at = datetime.now(timezone.utc) - timedelta(hours=25)

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

    async def test_not_abandoned_raises_value_error(self, restaurant_id):
        """Service-level: restore rejects non-abandoned sessions."""
        session_id = uuid.uuid4()
        mock_session = AsyncMock()

        open_session = MagicMock()
        open_session.id = session_id
        open_session.restaurant_id = restaurant_id
        open_session.table_id = uuid.uuid4()
        open_session.status = SessionStatus.OPEN
        open_session.abandoned_at = None

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = open_session
            return result

        mock_session.execute = _mock_execute

        with pytest.raises(ValueError, match="abandoned"):
            await SessionService.restore(
                session_id=session_id,
                restaurant_id=restaurant_id,
                session=mock_session,
            )

    async def test_session_not_found_returns_none(self, restaurant_id):
        """Service-level: returns None when session doesn't exist."""
        session_id = uuid.uuid4()
        mock_session = AsyncMock()

        call_count = 0

        async def _mock_execute(stmt, params=None):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if call_count == 1:
                result.scalar_one_or_none.return_value = None
            return result

        mock_session.execute = _mock_execute

        result = await SessionService.restore(
            session_id=session_id,
            restaurant_id=restaurant_id,
            session=mock_session,
        )

        assert result is None
