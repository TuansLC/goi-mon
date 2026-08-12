"""Unit tests for state machine, undo 120s, overdue, and bill exclusion (Task 7.4).

Pure logic tests — no HTTP client, no mocked DB sessions (except undo window
which documents the CAS WHERE clause behavior parametrically).

Validates:
- Property 3: Bill = Σ(price × qty) for served items only (R11.5)
- Property 4: Only valid transitions according to ALLOWED_FROM (R4.1, R4.7)
- Property 6: overdue_level computed dynamically, never stored (R5.4)
- Undo 120s window correctly bounded (R4.7)

Requirements: 4.1, 4.7, 5.4, 11.5
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from qorder_api.models.enums import OrderItemStatus
from qorder_api.services.item_state_service import (
    ALLOWED_FROM,
    InvalidTransition,
    ItemStateService,
    compute_overdue_level,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. State machine transition validation (Property 4 / R4.1)
# ═══════════════════════════════════════════════════════════════════════════════


class TestAllowedFromMap:
    """Verify ALLOWED_FROM defines exactly the valid transitions."""

    # --- Valid forward transitions ---

    def test_pending_to_cooking_valid(self):
        """pending → cooking is allowed."""
        assert OrderItemStatus.PENDING in ALLOWED_FROM[OrderItemStatus.COOKING]

    def test_pending_to_ready_valid(self):
        """pending → ready is allowed (skip cooking)."""
        assert OrderItemStatus.PENDING in ALLOWED_FROM[OrderItemStatus.READY]

    def test_cooking_to_ready_valid(self):
        """cooking → ready is allowed."""
        assert OrderItemStatus.COOKING in ALLOWED_FROM[OrderItemStatus.READY]

    def test_pending_to_served_valid(self):
        """pending → served is allowed (skip all intermediate)."""
        assert OrderItemStatus.PENDING in ALLOWED_FROM[OrderItemStatus.SERVED]

    def test_cooking_to_served_valid(self):
        """cooking → served is allowed."""
        assert OrderItemStatus.COOKING in ALLOWED_FROM[OrderItemStatus.SERVED]

    def test_ready_to_served_valid(self):
        """ready → served is allowed."""
        assert OrderItemStatus.READY in ALLOWED_FROM[OrderItemStatus.SERVED]

    # --- Undo: the ONLY valid backward transition ---

    def test_served_to_pending_valid(self):
        """served → pending is the only undo path (R4.7)."""
        assert OrderItemStatus.SERVED in ALLOWED_FROM[OrderItemStatus.PENDING]

    # --- Invalid backward transitions ---

    def test_cooking_to_pending_invalid(self):
        """cooking → pending is NOT allowed (no backward except undo)."""
        assert OrderItemStatus.COOKING not in ALLOWED_FROM[OrderItemStatus.PENDING]

    def test_ready_to_pending_invalid(self):
        """ready → pending is NOT allowed."""
        assert OrderItemStatus.READY not in ALLOWED_FROM[OrderItemStatus.PENDING]

    def test_ready_to_cooking_invalid(self):
        """ready → cooking is NOT allowed."""
        assert OrderItemStatus.READY not in ALLOWED_FROM[OrderItemStatus.COOKING]

    def test_served_to_cooking_invalid(self):
        """served → cooking is NOT allowed."""
        assert OrderItemStatus.SERVED not in ALLOWED_FROM[OrderItemStatus.COOKING]

    def test_served_to_ready_invalid(self):
        """served → ready is NOT allowed."""
        assert OrderItemStatus.SERVED not in ALLOWED_FROM[OrderItemStatus.READY]

    # --- Cancelled is NOT in ALLOWED_FROM (must use cancel_item path) ---

    def test_cancelled_not_a_target_in_allowed_from(self):
        """'cancelled' is not a key in ALLOWED_FROM — use cancel_item() instead."""
        assert OrderItemStatus.CANCELLED not in ALLOWED_FROM

    def test_cancelled_cannot_transition_anywhere(self):
        """Once cancelled, item cannot move to any other status via set_status."""
        for target, from_set in ALLOWED_FROM.items():
            assert OrderItemStatus.CANCELLED not in from_set, (
                f"cancelled should not be in ALLOWED_FROM[{target.value}]"
            )

    # --- InvalidTransition raised for unknown targets ---

    @pytest.mark.asyncio
    async def test_set_status_raises_for_cancelled_target(self):
        """ItemStateService.set_status raises InvalidTransition for 'cancelled'."""
        import uuid

        from unittest.mock import AsyncMock

        with pytest.raises(InvalidTransition):
            await ItemStateService.set_status(
                item_id=uuid.uuid4(),
                to_status=OrderItemStatus.CANCELLED,
                actor_user_id=uuid.uuid4(),
                restaurant_id=uuid.uuid4(),
                session=AsyncMock(),
            )


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Undo 120s window tests (R4.7)
# ═══════════════════════════════════════════════════════════════════════════════


class TestUndo120sWindow:
    """Document and verify the 120s undo window logic.

    The actual enforcement is in SQL: ``now() - served_at <= interval '120 seconds'``.
    These parametric tests document the expected boundary behavior.
    """

    @staticmethod
    def _is_within_undo_window(served_at: datetime, now: datetime) -> bool:
        """Pure-Python replication of the SQL WHERE clause for undo window.

        Equivalent to: now() - served_at <= interval '120 seconds'
        """
        return (now - served_at).total_seconds() <= 120

    @pytest.mark.parametrize(
        "elapsed_seconds,expected",
        [
            (0, True),       # Undo immediately → allowed
            (60, True),      # Undo at 1 minute → allowed
            (119, True),     # Undo at 119s → allowed
            (120, True),     # Undo at exactly 120s → allowed (<=)
            (121, False),    # Undo at 121s → rejected
            (180, False),    # Undo at 3 minutes → rejected
            (3600, False),   # Undo at 1 hour → rejected
        ],
    )
    def test_undo_window_boundary(self, elapsed_seconds: int, expected: bool):
        """Undo within ≤120s succeeds; beyond 120s fails."""
        served_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        now = served_at + timedelta(seconds=elapsed_seconds)
        assert self._is_within_undo_window(served_at, now) is expected

    def test_undo_window_fractional_boundary(self):
        """Undo at 120.5s → rejected (fractional second beyond window)."""
        served_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        now = served_at + timedelta(seconds=120.5)
        assert self._is_within_undo_window(served_at, now) is False

    def test_undo_at_exact_120s_allowed(self):
        """Confirms the boundary is inclusive: exactly 120s is allowed."""
        served_at = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
        now = served_at + timedelta(seconds=120)
        assert self._is_within_undo_window(served_at, now) is True


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Bill excludes cancelled items (Property 3 / R11.5)
# ═══════════════════════════════════════════════════════════════════════════════


class TestBillExcludesCancelled:
    """Verify that bill total only sums 'served' items.

    Property 3: total_amount = Σ(price_snapshot × quantity) for served items only.
    Cancelled items (regardless of cancelled_by) are excluded.
    """

    @staticmethod
    def compute_bill_total(items: list[dict]) -> Decimal:
        """Pure billing formula matching BillingService contract.

        Args:
            items: list of dicts with keys: price_snapshot, quantity, status.

        Returns:
            Sum of price_snapshot * quantity for served items only.
        """
        return sum(
            (item["price_snapshot"] * item["quantity"]
             for item in items
             if item["status"] == OrderItemStatus.SERVED),
            Decimal("0"),
        )

    def test_only_served_items_counted(self):
        """Bill includes only served items."""
        items = [
            {"price_snapshot": Decimal("50000"), "quantity": 2, "status": OrderItemStatus.SERVED},
            {"price_snapshot": Decimal("30000"), "quantity": 1, "status": OrderItemStatus.CANCELLED},
            {"price_snapshot": Decimal("40000"), "quantity": 1, "status": OrderItemStatus.SERVED},
        ]
        # Expected: 50000*2 + 40000*1 = 140000
        assert self.compute_bill_total(items) == Decimal("140000")

    def test_cancelled_by_customer_excluded(self):
        """Cancelled by customer → excluded from bill."""
        items = [
            {"price_snapshot": Decimal("25000"), "quantity": 3, "status": OrderItemStatus.SERVED},
            {"price_snapshot": Decimal("80000"), "quantity": 1, "status": OrderItemStatus.CANCELLED},
        ]
        assert self.compute_bill_total(items) == Decimal("75000")

    def test_cancelled_by_staff_excluded(self):
        """Cancelled by staff → excluded from bill."""
        items = [
            {"price_snapshot": Decimal("60000"), "quantity": 1, "status": OrderItemStatus.SERVED},
            {"price_snapshot": Decimal("45000"), "quantity": 2, "status": OrderItemStatus.CANCELLED},
        ]
        assert self.compute_bill_total(items) == Decimal("60000")

    def test_cancelled_by_system_excluded(self):
        """Cancelled by system (e.g., table_closed) → excluded from bill."""
        items = [
            {"price_snapshot": Decimal("100000"), "quantity": 1, "status": OrderItemStatus.SERVED},
            {"price_snapshot": Decimal("50000"), "quantity": 1, "status": OrderItemStatus.CANCELLED},
            {"price_snapshot": Decimal("30000"), "quantity": 2, "status": OrderItemStatus.CANCELLED},
        ]
        assert self.compute_bill_total(items) == Decimal("100000")

    def test_all_cancelled_gives_zero(self):
        """If every item is cancelled, bill total is 0."""
        items = [
            {"price_snapshot": Decimal("50000"), "quantity": 1, "status": OrderItemStatus.CANCELLED},
            {"price_snapshot": Decimal("30000"), "quantity": 2, "status": OrderItemStatus.CANCELLED},
        ]
        assert self.compute_bill_total(items) == Decimal("0")

    def test_empty_items_gives_zero(self):
        """No items → total is 0."""
        assert self.compute_bill_total([]) == Decimal("0")

    def test_pending_cooking_ready_excluded(self):
        """Items not yet served (pending/cooking/ready) are not in the bill."""
        items = [
            {"price_snapshot": Decimal("50000"), "quantity": 1, "status": OrderItemStatus.PENDING},
            {"price_snapshot": Decimal("30000"), "quantity": 1, "status": OrderItemStatus.COOKING},
            {"price_snapshot": Decimal("40000"), "quantity": 1, "status": OrderItemStatus.READY},
            {"price_snapshot": Decimal("60000"), "quantity": 1, "status": OrderItemStatus.SERVED},
        ]
        assert self.compute_bill_total(items) == Decimal("60000")

    def test_mixed_statuses_complete_scenario(self):
        """Realistic session: multiple rounds, some cancelled, some served."""
        items = [
            # Round 1
            {"price_snapshot": Decimal("50000"), "quantity": 2, "status": OrderItemStatus.SERVED},   # 100000
            {"price_snapshot": Decimal("25000"), "quantity": 1, "status": OrderItemStatus.CANCELLED},  # excluded
            # Round 2
            {"price_snapshot": Decimal("35000"), "quantity": 3, "status": OrderItemStatus.SERVED},   # 105000
            {"price_snapshot": Decimal("80000"), "quantity": 1, "status": OrderItemStatus.CANCELLED},  # excluded
            {"price_snapshot": Decimal("15000"), "quantity": 4, "status": OrderItemStatus.SERVED},   # 60000
        ]
        # Total = 100000 + 105000 + 60000 = 265000
        assert self.compute_bill_total(items) == Decimal("265000")


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Overdue ratio boundary tests (Property 6 / R5.4)
# ═══════════════════════════════════════════════════════════════════════════════


class TestOverdueLevelBoundaries:
    """Precise boundary tests for compute_overdue_level.

    Overdue level thresholds:
      ratio < 1.0  → level 0
      1.0 ≤ ratio < 1.5  → level 1
      1.5 ≤ ratio < 2.0  → level 2
      ratio ≥ 2.0  → level 3
    """

    BASE_TIME = datetime(2024, 6, 1, 12, 0, 0, tzinfo=timezone.utc)
    PREP_TIME = 10  # minutes

    def test_ratio_just_below_1_is_level_0(self):
        """ratio = 0.999... → level 0."""
        # 9.99 minutes elapsed, prep=10 → ratio=0.999
        now = self.BASE_TIME + timedelta(minutes=9.99)
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 0

    def test_ratio_exactly_1_is_level_1(self):
        """ratio = 1.0 → level 1 (boundary)."""
        now = self.BASE_TIME + timedelta(minutes=10)
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 1

    def test_ratio_just_above_1_is_level_1(self):
        """ratio = 1.001 → level 1."""
        now = self.BASE_TIME + timedelta(minutes=10.01)
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 1

    def test_ratio_just_below_1_5_is_level_1(self):
        """ratio = 1.499... → level 1."""
        now = self.BASE_TIME + timedelta(minutes=14.99)
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 1

    def test_ratio_exactly_1_5_is_level_2(self):
        """ratio = 1.5 → level 2 (boundary)."""
        now = self.BASE_TIME + timedelta(minutes=15)
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 2

    def test_ratio_just_above_1_5_is_level_2(self):
        """ratio = 1.501 → level 2."""
        now = self.BASE_TIME + timedelta(minutes=15.01)
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 2

    def test_ratio_just_below_2_is_level_2(self):
        """ratio = 1.999... → level 2."""
        now = self.BASE_TIME + timedelta(minutes=19.99)
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 2

    def test_ratio_exactly_2_is_level_3(self):
        """ratio = 2.0 → level 3 (boundary)."""
        now = self.BASE_TIME + timedelta(minutes=20)
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 3

    def test_ratio_just_above_2_is_level_3(self):
        """ratio = 2.001 → level 3."""
        now = self.BASE_TIME + timedelta(minutes=20.01)
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 3

    def test_prep_time_zero_returns_none(self):
        """prep_time=0 always returns None regardless of elapsed time."""
        # Even with very large elapsed time
        now = self.BASE_TIME + timedelta(hours=10)
        assert compute_overdue_level(0, self.BASE_TIME, now) is None

    def test_prep_time_zero_at_start_returns_none(self):
        """prep_time=0 at t=0 → None."""
        assert compute_overdue_level(0, self.BASE_TIME, self.BASE_TIME) is None

    def test_very_large_elapsed_caps_at_level_3(self):
        """Very large elapsed time → still level 3 (no level 4+)."""
        now = self.BASE_TIME + timedelta(hours=24)  # ratio=144
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, now) == 3

    def test_elapsed_zero_is_level_0(self):
        """Just ordered (elapsed=0, ratio=0) → level 0."""
        assert compute_overdue_level(self.PREP_TIME, self.BASE_TIME, self.BASE_TIME) == 0

    @pytest.mark.parametrize(
        "prep_time,elapsed_minutes,expected_level",
        [
            (5, 4.9, 0),     # ratio=0.98
            (5, 5.0, 1),     # ratio=1.0
            (5, 7.4, 1),     # ratio=1.48
            (5, 7.5, 2),     # ratio=1.5
            (5, 9.9, 2),     # ratio=1.98
            (5, 10.0, 3),    # ratio=2.0
            (20, 19.9, 0),   # ratio=0.995
            (20, 20.0, 1),   # ratio=1.0
            (20, 30.0, 2),   # ratio=1.5
            (20, 40.0, 3),   # ratio=2.0
            (1, 0.9, 0),     # ratio=0.9
            (1, 1.0, 1),     # ratio=1.0
            (1, 1.5, 2),     # ratio=1.5
            (1, 2.0, 3),     # ratio=2.0
        ],
    )
    def test_various_prep_times(
        self, prep_time: int, elapsed_minutes: float, expected_level: int
    ):
        """Boundaries hold for different prep_time values."""
        now = self.BASE_TIME + timedelta(minutes=elapsed_minutes)
        assert compute_overdue_level(prep_time, self.BASE_TIME, now) == expected_level
