"""ESC/POS thermal printer integration (R6.3).

Uses ``python-escpos`` to connect to a thermal receipt printer via USB or
network. Falls back gracefully if the library is not installed or the printer
is unreachable.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from qorder_api.printing.models import BillData, BillResult

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _format_price(amount, currency: str) -> str:
    """Format a price value for receipt display."""
    if currency == "VND":
        return f"{int(amount):,}đ".replace(",", ".")
    return f"{amount} {currency}"


def print_thermal(bill: BillData, *, printer_type: str, printer_ip: str | None, printer_port: int) -> BillResult:
    """Attempt to print a bill via ESC/POS thermal printer.

    Parameters
    ----------
    bill : BillData
        The bill content to print.
    printer_type : str
        "usb", "network", or "none".
    printer_ip : str | None
        IP address for network printers.
    printer_port : int
        Port for network printers (default 9100).

    Returns
    -------
    BillResult
        Result with method="thermal" on success, or method="failed" with error.
    """
    if printer_type == "none":
        return BillResult(method="failed", error="No thermal printer configured (printer_type='none')")

    try:
        from escpos.printer import Network, Usb  # type: ignore[import-untyped]
    except ImportError:
        return BillResult(
            method="failed",
            error="python-escpos is not installed. Install with: pip install 'qorder-api[printing]'",
        )

    try:
        # Connect to printer
        if printer_type == "network":
            if not printer_ip:
                return BillResult(method="failed", error="printer_ip is required for network printer")
            printer = Network(printer_ip, port=printer_port)
        elif printer_type == "usb":
            # Default USB vendor/product IDs — most common thermal printers.
            # In production these would come from config.
            printer = Usb(0x0416, 0x5011)
        else:
            return BillResult(method="failed", error=f"Unknown printer_type: {printer_type!r}")

        # --- Format and print the receipt ---

        # Header: restaurant name (centered, bold)
        printer.set(align="center", bold=True, double_height=True, double_width=True)
        printer.text(f"{bill.restaurant_name}\n")

        # Table label
        printer.set(align="center", bold=False, double_height=False, double_width=False)
        printer.text(f"Ban: {bill.table_label}\n")

        # Separator
        printer.text("-" * 32 + "\n")

        # Items
        printer.set(align="left", bold=False)
        for item in bill.items:
            line_price = _format_price(item.unit_price * item.quantity, bill.currency)
            printer.text(f"{item.name}\n")
            printer.text(f"  {item.quantity} x {_format_price(item.unit_price, bill.currency)} = {line_price}\n")

        # Separator
        printer.text("-" * 32 + "\n")

        # Total (bold)
        printer.set(align="right", bold=True)
        printer.text(f"TONG: {_format_price(bill.total_amount, bill.currency)}\n")

        # Timestamp
        printer.set(align="center", bold=False)
        printer.text(f"{bill.closed_at.strftime('%d/%m/%Y %H:%M')}\n")
        printer.text("\n")

        # Cut paper
        printer.cut()

        logger.info("Bill printed via thermal printer for table %s", bill.table_label)
        return BillResult(method="thermal")

    except Exception as exc:  # noqa: BLE001
        logger.warning("Thermal printing failed: %s", exc)
        return BillResult(method="failed", error=f"Thermal printing error: {exc}")
