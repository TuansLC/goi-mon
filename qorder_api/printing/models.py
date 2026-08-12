"""Data models for the bill printing service (R6.3, R6.4, R6.5)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Literal


@dataclass(frozen=True, slots=True)
class BillItem:
    """A single line item on a bill receipt."""

    name: str
    quantity: int
    unit_price: Decimal


@dataclass(frozen=True, slots=True)
class BillData:
    """All data required to render a bill receipt.

    Fields correspond to R6.5:
    - restaurant_name: tên quán
    - table_label: số bàn
    - items: danh sách món + SL + đơn giá
    - total_amount: tổng tiền
    - currency: đơn vị tiền tệ
    - closed_at: thời gian thanh toán
    """

    restaurant_name: str
    table_label: str
    items: list[BillItem]
    total_amount: Decimal
    currency: str  # e.g. "VND"
    closed_at: datetime


@dataclass(frozen=True, slots=True)
class BillResult:
    """Outcome of a print_bill attempt.

    method:
      - "thermal": printed via ESC/POS successfully
      - "pdf": thermal failed, PDF generated as fallback
      - "failed": both paths failed
    """

    method: Literal["thermal", "pdf", "failed"]
    pdf_path: str | None = None
    error: str | None = None
