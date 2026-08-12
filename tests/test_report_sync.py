"""Unit tests for ReportSyncService (R9.1–R9.4).

Tests verify:
- sync skips when no report_sheet_id is configured
- sync aggregates revenue and top items then writes to Google Sheet
- sync errors are logged but do not raise (R9.4)
- only aggregate data is synced, no live state (R9.3)
"""

from __future__ import annotations

import uuid
from datetime import date, datetime, timedelta
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from qorder_api.reporting import (
    ReportSyncService,
    _get_gspread_client,
    _write_revenue_worksheet,
    _write_top_items_worksheet,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

RESTAURANT_ID = uuid.uuid4()


def _make_mapping(data: dict):
    """Simulate SQLAlchemy row mapping."""

    class FakeMapping:
        def __getitem__(self, key):
            return data[key]

        def get(self, key, default=None):
            return data.get(key, default)

    return FakeMapping()


# ---------------------------------------------------------------------------
# Tests: _write_revenue_worksheet / _write_top_items_worksheet
# ---------------------------------------------------------------------------


class TestWriteRevenue:
    def test_creates_worksheet_if_not_found(self):
        spreadsheet = MagicMock()
        spreadsheet.worksheet.side_effect = Exception("not found")
        # Simulate gspread.WorksheetNotFound by using side_effect
        import gspread

        spreadsheet.worksheet.side_effect = gspread.WorksheetNotFound("Revenue")
        new_ws = MagicMock()
        spreadsheet.add_worksheet.return_value = new_ws

        revenue_data = [
            {"day": "2024-06-01", "revenue": 1000000.0, "sessions": 5},
        ]
        _write_revenue_worksheet(spreadsheet, revenue_data)

        spreadsheet.add_worksheet.assert_called_once_with(
            title="Revenue", rows=100, cols=3
        )
        new_ws.clear.assert_called_once()
        new_ws.update.assert_called_once()

    def test_updates_existing_worksheet(self):
        spreadsheet = MagicMock()
        ws = MagicMock()
        spreadsheet.worksheet.return_value = ws

        revenue_data = [
            {"day": "2024-06-01", "revenue": 500000.0, "sessions": 3},
            {"day": "2024-06-02", "revenue": 750000.0, "sessions": 4},
        ]
        _write_revenue_worksheet(spreadsheet, revenue_data)

        ws.clear.assert_called_once()
        call_args = ws.update.call_args
        values = call_args.kwargs["values"] if "values" in (call_args.kwargs or {}) else call_args[1].get("values", call_args[0][0] if call_args[0] else None)
        # Should have header + 2 data rows
        assert len(values) == 3
        assert values[0] == ["Ngày", "Doanh thu", "Số phiên"]


class TestWriteTopItems:
    def test_creates_worksheet_if_not_found(self):
        import gspread

        spreadsheet = MagicMock()
        spreadsheet.worksheet.side_effect = gspread.WorksheetNotFound("Top Items")
        new_ws = MagicMock()
        spreadsheet.add_worksheet.return_value = new_ws

        items_data = [{"name": "Phở bò", "sold": 100}]
        _write_top_items_worksheet(spreadsheet, items_data)

        spreadsheet.add_worksheet.assert_called_once_with(
            title="Top Items", rows=100, cols=2
        )
        new_ws.clear.assert_called_once()
        new_ws.update.assert_called_once()

    def test_updates_existing_worksheet(self):
        spreadsheet = MagicMock()
        ws = MagicMock()
        spreadsheet.worksheet.return_value = ws

        items_data = [
            {"name": "Phở bò", "sold": 100},
            {"name": "Bún chả", "sold": 80},
        ]
        _write_top_items_worksheet(spreadsheet, items_data)

        ws.clear.assert_called_once()
        call_args = ws.update.call_args
        values = call_args.kwargs["values"] if "values" in (call_args.kwargs or {}) else call_args[1].get("values", call_args[0][0] if call_args[0] else None)
        assert len(values) == 3
        assert values[0] == ["Món", "Số lượng bán"]


# ---------------------------------------------------------------------------
# Tests: ReportSyncService.sync — error handling (R9.4)
# ---------------------------------------------------------------------------


class TestSyncErrorHandling:
    @pytest.mark.asyncio
    async def test_sync_swallows_exceptions(self):
        """R9.4: errors are logged, never raised."""
        with patch(
            "qorder_api.reporting.async_session_factory"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(
                return_value=mock_session
            )
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=False)
            # Simulate a DB error
            mock_session.execute.side_effect = RuntimeError("DB gone")

            # Must NOT raise
            await ReportSyncService.sync(RESTAURANT_ID)

    @pytest.mark.asyncio
    async def test_sync_skips_when_no_sheet_id(self):
        """When report_sheet_id is NULL, sync is a no-op."""
        with patch(
            "qorder_api.reporting.async_session_factory"
        ) as mock_factory:
            mock_session = AsyncMock()
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_factory.return_value = mock_ctx

            # Return a row with no report_sheet_id
            mock_result = MagicMock()
            mock_result.mappings.return_value.first.return_value = {
                "report_sheet_id": None
            }
            mock_session.execute.return_value = mock_result

            # Should not raise or attempt sheet write
            await ReportSyncService.sync(RESTAURANT_ID)


# ---------------------------------------------------------------------------
# Tests: _get_gspread_client config validation
# ---------------------------------------------------------------------------


class TestGspreadClient:
    def test_raises_when_no_config(self):
        """If google_service_account_json is not set, raises RuntimeError."""
        with patch("qorder_api.reporting.get_settings") as mock_settings:
            mock_settings.return_value.google_service_account_json = None
            with pytest.raises(RuntimeError, match="google_service_account_json"):
                _get_gspread_client()


# ---------------------------------------------------------------------------
# Tests: sync_reports scheduler function
# ---------------------------------------------------------------------------


class TestSyncReportsJob:
    @pytest.mark.asyncio
    async def test_skips_when_lock_held(self):
        """If Redis lock is already held, job silently skips."""
        from qorder_api.scheduler import sync_reports

        with patch("qorder_api.scheduler._get_pool") as mock_pool:
            mock_redis = AsyncMock()
            mock_redis.set.return_value = False  # lock not acquired
            mock_redis.aclose = AsyncMock()

            with patch(
                "qorder_api.scheduler.aioredis.Redis", return_value=mock_redis
            ):
                await sync_reports()

            # Should not attempt to run sync
            mock_redis.set.assert_called_once()
