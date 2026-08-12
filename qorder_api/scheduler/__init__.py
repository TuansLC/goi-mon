"""APScheduler jobs (auto-abandon sweep, report sync) with Redis locking.

Provides:
- ``sweep_abandoned_sessions()`` — find and abandon stale open sessions (R13.2–R13.4, R13.8).
- ``sync_reports()`` — aggregate revenue/items → Google Sheet per restaurant (R9).
- ``start_scheduler()`` / ``shutdown_scheduler()`` — lifecycle tied to FastAPI lifespan.

The sweep uses:
1. A Redis distributed lock (``SET NX EX``) so only one instance runs the job
   when multiple replicas are deployed.
2. CAS (``UPDATE ... WHERE status='open' RETURNING *``) per session so the sweep
   never races with a concurrent checkout.
"""

from __future__ import annotations

import logging
import uuid as _uuid

import redis.asyncio as aioredis
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from qorder_api.config import get_settings
from qorder_api.db import async_session_factory
from qorder_api.realtime import (
    EventTypes,
    RealtimePublisher,
    kitchen_channel,
    session_channel,
)
from qorder_api.redis import _get_pool
from qorder_api.services.staff_call_service import StaffCallService

logger = logging.getLogger(__name__)

_scheduler: AsyncIOScheduler | None = None

# Unique identifier for this process instance (used as lock value).
_INSTANCE_ID = str(_uuid.uuid4())

# Redis keys for distributed locks.
_LOCK_KEY = "lock:job:abandon_sweep"
_REPORT_LOCK_KEY = "lock:job:report_sync"


# ---------------------------------------------------------------------------
# Sweep logic
# ---------------------------------------------------------------------------


async def sweep_abandoned_sessions() -> None:
    """Run the auto-abandon sweep for all restaurants.

    Acquires a Redis distributed lock before proceeding. If the lock cannot be
    acquired (another instance already running), silently skips this run.
    """
    settings = get_settings()
    lock_ttl = settings.scheduler_lock_ttl_seconds

    # Get a Redis client for the lock and pub/sub
    redis_client = aioredis.Redis(connection_pool=_get_pool())
    try:
        # 1. Acquire distributed lock (SET NX EX)
        acquired = await redis_client.set(
            _LOCK_KEY, _INSTANCE_ID, nx=True, ex=lock_ttl
        )
        if not acquired:
            logger.debug("Abandon sweep: lock held by another instance, skipping.")
            return

        logger.info("Abandon sweep: lock acquired, starting scan.")

        try:
            await _run_sweep(redis_client)
        finally:
            # Release lock only if we still hold it (compare value).
            current_holder = await redis_client.get(_LOCK_KEY)
            if current_holder == _INSTANCE_ID:
                await redis_client.delete(_LOCK_KEY)
                logger.debug("Abandon sweep: lock released.")
    except Exception:
        logger.exception("Abandon sweep: unexpected error.")
    finally:
        await redis_client.aclose()


async def _run_sweep(redis_client: aioredis.Redis) -> None:
    """Core sweep: find stale sessions and CAS-abandon them."""
    from sqlalchemy import text

    async with async_session_factory() as db:
        # Find all open sessions past timeout across all restaurants.
        # Join restaurant_settings to get per-restaurant timeout.
        stale_sessions = await db.execute(
            text("""
                SELECT ts.id, ts.restaurant_id, ts.table_id
                FROM table_sessions ts
                JOIN restaurant_settings rs
                  ON rs.restaurant_id = ts.restaurant_id
                WHERE ts.status = 'open'
                  AND ts.last_activity_at < now() - make_interval(hours => rs.session_timeout_hours)
            """)
        )
        rows = stale_sessions.mappings().all()

        if not rows:
            logger.info("Abandon sweep: no stale sessions found.")
            return

        logger.info("Abandon sweep: found %d stale session(s) to process.", len(rows))

        for row in rows:
            session_id = row["id"]
            restaurant_id = row["restaurant_id"]

            try:
                await _abandon_session(db, session_id, restaurant_id, redis_client)
            except Exception:
                logger.exception(
                    "Abandon sweep: error processing session %s", session_id
                )
                # Rollback the failed sub-transaction, continue with others
                await db.rollback()


async def _abandon_session(
    db,
    session_id: _uuid.UUID,
    restaurant_id: _uuid.UUID,
    redis_client: aioredis.Redis,
) -> None:
    """CAS-abandon a single session and handle side effects."""
    from sqlalchemy import text

    # 1. CAS: mark session abandoned only if still open
    cas_result = await db.execute(
        text("""
            UPDATE table_sessions
            SET status = 'abandoned',
                abandoned_at = now(),
                total_amount = NULL
            WHERE id = :session_id
              AND status = 'open'
            RETURNING id, restaurant_id
        """),
        {"session_id": session_id},
    )
    abandoned_row = cas_result.mappings().first()

    if abandoned_row is None:
        # CAS lost: session was closed/abandoned by someone else — skip
        logger.debug(
            "Abandon sweep: session %s already closed/abandoned, skipping.", session_id
        )
        return

    # 2. Auto-cancel all unserved items (R13.8)
    cancel_result = await db.execute(
        text("""
            UPDATE order_items
            SET status = 'cancelled',
                cancelled_by = 'system',
                cancelled_at = now(),
                cancel_reason = 'session_abandoned'
            WHERE order_id IN (
                SELECT id FROM orders WHERE table_session_id = :session_id
            )
            AND status IN ('pending', 'cooking', 'ready')
        """),
        {"session_id": session_id},
    )
    cancelled_count = cancel_result.rowcount

    # 3. Dismiss pending staff calls (reuse from task 9.1)
    dismissed_count = await StaffCallService.dismiss_pending(
        session_id=session_id,
        restaurant_id=restaurant_id,
        session=db,
    )

    # 4. Commit all changes for this session
    await db.commit()

    logger.info(
        "Abandon sweep: session %s abandoned (cancelled %d items, dismissed %d calls).",
        session_id,
        cancelled_count,
        dismissed_count,
    )

    # 5. Publish session.abandoned event (fire-and-forget)
    payload = {
        "session_id": str(session_id),
        "restaurant_id": str(restaurant_id),
    }
    await RealtimePublisher.publish(
        kitchen_channel(restaurant_id),
        EventTypes.SESSION_ABANDONED,
        payload,
        redis_client,
    )
    await RealtimePublisher.publish(
        session_channel(restaurant_id, session_id),
        EventTypes.SESSION_ABANDONED,
        payload,
        redis_client,
    )


# ---------------------------------------------------------------------------
# Report sync logic (R9)
# ---------------------------------------------------------------------------


async def sync_reports() -> None:
    """Run report sync for all restaurants with a configured report_sheet_id.

    Acquires a Redis distributed lock before proceeding. If the lock cannot be
    acquired (another instance already running), silently skips this run.
    Errors per restaurant are logged but do not halt the loop (R9.4).
    """
    settings = get_settings()
    lock_ttl = settings.scheduler_lock_ttl_seconds

    redis_client = aioredis.Redis(connection_pool=_get_pool())
    try:
        acquired = await redis_client.set(
            _REPORT_LOCK_KEY, _INSTANCE_ID, nx=True, ex=lock_ttl
        )
        if not acquired:
            logger.debug("Report sync: lock held by another instance, skipping.")
            return

        logger.info("Report sync: lock acquired, starting sync.")

        try:
            await _run_report_sync()
        finally:
            current_holder = await redis_client.get(_REPORT_LOCK_KEY)
            if current_holder == _INSTANCE_ID:
                await redis_client.delete(_REPORT_LOCK_KEY)
                logger.debug("Report sync: lock released.")
    except Exception:
        logger.exception("Report sync: unexpected error.")
    finally:
        await redis_client.aclose()


async def _run_report_sync() -> None:
    """Iterate restaurants with report_sheet_id and sync each."""
    from sqlalchemy import text

    from qorder_api.reporting import ReportSyncService

    async with async_session_factory() as db:
        result = await db.execute(
            text(
                "SELECT restaurant_id FROM restaurant_settings WHERE report_sheet_id IS NOT NULL"
            )
        )
        restaurant_ids = [row["restaurant_id"] for row in result.mappings().all()]

    if not restaurant_ids:
        logger.info("Report sync: no restaurants with report_sheet_id configured.")
        return

    logger.info("Report sync: syncing %d restaurant(s).", len(restaurant_ids))

    for rid in restaurant_ids:
        try:
            await ReportSyncService.sync(rid)
        except Exception:
            # Individual failures don't block others (R9.4)
            logger.exception("Report sync: error syncing restaurant %s", rid)


# ---------------------------------------------------------------------------
# Scheduler lifecycle
# ---------------------------------------------------------------------------


def start_scheduler() -> None:
    """Create and start the APScheduler AsyncIOScheduler.

    Registers the abandon sweep job at the configured interval and the report
    sync job using the default cron schedule (every hour).
    Call this during FastAPI startup (lifespan).
    """
    global _scheduler
    settings = get_settings()

    _scheduler = AsyncIOScheduler()
    _scheduler.add_job(
        sweep_abandoned_sessions,
        trigger="interval",
        minutes=settings.abandon_sweep_interval_minutes,
        id="abandon_sweep",
        replace_existing=True,
    )

    # Report sync job — default cron "0 * * * *" (hourly)
    # Uses a CronTrigger so restaurants can override per-restaurant cron later
    # but the job itself runs hourly and iterates all restaurants.
    _scheduler.add_job(
        sync_reports,
        trigger=CronTrigger.from_crontab("0 * * * *"),
        id="report_sync",
        replace_existing=True,
    )

    _scheduler.start()
    logger.info(
        "Scheduler started: abandon sweep every %d minutes, report sync hourly.",
        settings.abandon_sweep_interval_minutes,
    )


def shutdown_scheduler() -> None:
    """Gracefully shut down the scheduler.

    Call this during FastAPI shutdown (lifespan).
    """
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        logger.info("Scheduler shut down.")
        _scheduler = None
