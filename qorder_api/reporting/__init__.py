"""Google Sheets report sync service (R9).

Aggregates revenue-per-day and top-selling items, then writes them to the
restaurant's configured Google Sheet via gspread + Service Account.

Important:
- Only summary/aggregate data is synced (R9.3 — NO live state).
- Failures are logged and retried on the next scheduled run (R9.4).
"""

from __future__ import annotations

import logging
import uuid
from datetime import date, timedelta

import gspread
from google.oauth2.service_account import Credentials

from qorder_api.config import get_settings
from qorder_api.db import async_session_factory

logger = logging.getLogger(__name__)

# Scopes required for Sheets read/write
_SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]


class ReportSyncService:
    """Sync aggregate report data to Google Sheets for a single restaurant."""

    @staticmethod
    async def sync(restaurant_id: uuid.UUID) -> None:
        """Run the full sync cycle for one restaurant.

        Steps:
          1. Load restaurant settings (report_sheet_id).
          2. Query DB for daily revenue (closed sessions).
          3. Query DB for top-selling items (served order_items).
          4. Write results to Google Sheet worksheets.

        Errors are caught, logged, and swallowed so app operation is unaffected (R9.4).
        """
        try:
            await _do_sync(restaurant_id)
        except Exception:
            logger.exception(
                "ReportSyncService: sync failed for restaurant %s — will retry next run.",
                restaurant_id,
            )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


async def _do_sync(restaurant_id: uuid.UUID) -> None:
    """Core sync logic (may raise)."""
    from sqlalchemy import text

    async with async_session_factory() as db:
        # 1. Get report_sheet_id
        row = await db.execute(
            text(
                "SELECT report_sheet_id FROM restaurant_settings WHERE restaurant_id = :rid"
            ),
            {"rid": restaurant_id},
        )
        settings_row = row.mappings().first()
        if not settings_row or not settings_row["report_sheet_id"]:
            logger.debug(
                "ReportSyncService: restaurant %s has no report_sheet_id, skipping.",
                restaurant_id,
            )
            return

        sheet_id: str = settings_row["report_sheet_id"]

        # 2. Daily revenue (last 30 days of closed sessions)
        since = date.today() - timedelta(days=30)
        revenue_rows = await db.execute(
            text("""
                SELECT closed_at::date AS day,
                       SUM(total_amount) AS revenue,
                       COUNT(*) AS sessions_count
                FROM table_sessions
                WHERE restaurant_id = :rid
                  AND status = 'closed'
                  AND closed_at >= :since
                GROUP BY closed_at::date
                ORDER BY day
            """),
            {"rid": restaurant_id, "since": since},
        )
        revenue_data = [
            {
                "day": str(r["day"]),
                "revenue": float(r["revenue"]) if r["revenue"] else 0,
                "sessions": int(r["sessions_count"]),
            }
            for r in revenue_rows.mappings().all()
        ]

        # 3. Top-selling items (last 30 days, served items)
        top_items_rows = await db.execute(
            text("""
                SELECT oi.name_snapshot,
                       SUM(oi.quantity) AS total_sold
                FROM order_items oi
                JOIN orders o ON o.id = oi.order_id
                WHERE oi.restaurant_id = :rid
                  AND oi.status = 'served'
                  AND oi.served_at >= :since
                GROUP BY oi.name_snapshot
                ORDER BY total_sold DESC
                LIMIT 50
            """),
            {"rid": restaurant_id, "since": since},
        )
        top_items_data = [
            {"name": r["name_snapshot"], "sold": int(r["total_sold"])}
            for r in top_items_rows.mappings().all()
        ]

    # 4. Write to Google Sheet (sync I/O — gspread is synchronous)
    _write_to_sheet(sheet_id, revenue_data, top_items_data)

    logger.info(
        "ReportSyncService: synced restaurant %s (%d revenue rows, %d top items).",
        restaurant_id,
        len(revenue_data),
        len(top_items_data),
    )


def _get_gspread_client() -> gspread.Client:
    """Create an authorized gspread client using the configured Service Account."""
    settings = get_settings()
    sa_path = settings.google_service_account_json
    if not sa_path:
        raise RuntimeError(
            "google_service_account_json is not configured — cannot sync reports."
        )

    credentials = Credentials.from_service_account_file(sa_path, scopes=_SCOPES)
    return gspread.authorize(credentials)


def _write_to_sheet(
    sheet_id: str,
    revenue_data: list[dict],
    top_items_data: list[dict],
) -> None:
    """Write revenue and top-items data to the Google Sheet."""
    gc = _get_gspread_client()
    spreadsheet = gc.open_by_key(sheet_id)

    # --- Revenue worksheet ---
    _write_revenue_worksheet(spreadsheet, revenue_data)

    # --- Top Items worksheet ---
    _write_top_items_worksheet(spreadsheet, top_items_data)


def _write_revenue_worksheet(
    spreadsheet: gspread.Spreadsheet,
    revenue_data: list[dict],
) -> None:
    """Create/update the 'Revenue' worksheet with daily revenue data."""
    try:
        ws = spreadsheet.worksheet("Revenue")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="Revenue", rows=100, cols=3)

    # Clear existing data and write header + rows
    ws.clear()
    header = ["Ngày", "Doanh thu", "Số phiên"]
    rows = [[r["day"], r["revenue"], r["sessions"]] for r in revenue_data]
    ws.update(values=[header] + rows, range_name="A1")


def _write_top_items_worksheet(
    spreadsheet: gspread.Spreadsheet,
    top_items_data: list[dict],
) -> None:
    """Create/update the 'Top Items' worksheet with best-selling items."""
    try:
        ws = spreadsheet.worksheet("Top Items")
    except gspread.WorksheetNotFound:
        ws = spreadsheet.add_worksheet(title="Top Items", rows=100, cols=2)

    ws.clear()
    header = ["Món", "Số lượng bán"]
    rows = [[item["name"], item["sold"]] for item in top_items_data]
    ws.update(values=[header] + rows, range_name="A1")
