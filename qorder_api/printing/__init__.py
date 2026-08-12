"""Bill printing: ESC/POS thermal printer with PDF fallback (R6.3, R6.4, R6.5).

Public API
----------
- :class:`BillData` — input data for a bill
- :class:`BillItem` — single item on a bill
- :class:`BillResult` — outcome of a print attempt
- :class:`PrintingService` — orchestrates thermal → PDF fallback
"""

from __future__ import annotations

import logging

from qorder_api.printing.models import BillData, BillItem, BillResult

logger = logging.getLogger(__name__)

__all__ = [
    "BillData",
    "BillItem",
    "BillResult",
    "PrintingService",
]


class PrintingService:
    """Orchestrates bill printing: ESC/POS thermal with PDF fallback.

    Usage::

        from qorder_api.printing import PrintingService, BillData, BillItem
        from qorder_api.config import get_settings

        settings = get_settings()
        service = PrintingService(settings)
        result = service.print_bill(bill_data)
    """

    def __init__(
        self,
        *,
        printer_type: str = "none",
        printer_ip: str | None = None,
        printer_port: int = 9100,
        bill_pdf_output_dir: str = "/tmp/qorder_bills",
    ) -> None:
        self._printer_type = printer_type
        self._printer_ip = printer_ip
        self._printer_port = printer_port
        self._pdf_output_dir = bill_pdf_output_dir

    @classmethod
    def from_settings(cls, settings) -> "PrintingService":
        """Create a PrintingService from the application Settings object."""
        return cls(
            printer_type=settings.printer_type,
            printer_ip=settings.printer_ip,
            printer_port=settings.printer_port,
            bill_pdf_output_dir=settings.bill_pdf_output_dir,
        )

    def print_bill(self, bill: BillData) -> BillResult:
        """Print a bill, falling back from thermal to PDF on failure.

        This method is designed to be fire-and-forget safe — it will never
        raise an exception. All errors are captured in the returned BillResult.

        Strategy:
          1. Try ESC/POS thermal printing
          2. If thermal fails → try PDF generation
          3. If both fail → return failed result with combined error info
        """
        from qorder_api.printing.escpos_printer import print_thermal
        from qorder_api.printing.pdf_printer import print_pdf

        # Step 1: try thermal
        thermal_result = print_thermal(
            bill,
            printer_type=self._printer_type,
            printer_ip=self._printer_ip,
            printer_port=self._printer_port,
        )

        if thermal_result.method == "thermal":
            return thermal_result

        # Step 2: thermal failed, try PDF fallback
        logger.info(
            "Thermal printing failed (%s), falling back to PDF",
            thermal_result.error,
        )
        pdf_result = print_pdf(bill, output_dir=self._pdf_output_dir)

        if pdf_result.method == "pdf":
            return pdf_result

        # Step 3: both failed
        combined_error = (
            f"Thermal: {thermal_result.error}; PDF: {pdf_result.error}"
        )
        logger.error("All printing methods failed: %s", combined_error)
        return BillResult(method="failed", error=combined_error)
