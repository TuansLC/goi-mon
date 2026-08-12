"""Unit tests for the PrintingService (R6.3, R6.4, R6.5)."""

from datetime import datetime
from decimal import Decimal
from unittest.mock import patch

import pytest

from qorder_api.printing import BillData, BillItem, BillResult, PrintingService


@pytest.fixture()
def sample_bill() -> BillData:
    return BillData(
        restaurant_name="Quán Phở 24",
        table_label="B3",
        items=[
            BillItem(name="Phở bò tái", quantity=2, unit_price=Decimal("55000")),
            BillItem(name="Gỏi cuốn", quantity=1, unit_price=Decimal("35000")),
        ],
        total_amount=Decimal("145000"),
        currency="VND",
        closed_at=datetime(2024, 6, 15, 14, 30, 0),
    )


class TestBillModels:
    """Verify data model structure."""

    def test_bill_item_frozen(self):
        item = BillItem(name="Cà phê", quantity=1, unit_price=Decimal("25000"))
        assert item.name == "Cà phê"
        assert item.quantity == 1
        assert item.unit_price == Decimal("25000")
        with pytest.raises(Exception):
            item.name = "Other"  # type: ignore[misc]

    def test_bill_data_fields(self, sample_bill: BillData):
        assert sample_bill.restaurant_name == "Quán Phở 24"
        assert sample_bill.table_label == "B3"
        assert len(sample_bill.items) == 2
        assert sample_bill.total_amount == Decimal("145000")
        assert sample_bill.currency == "VND"

    def test_bill_result_defaults(self):
        result = BillResult(method="thermal")
        assert result.pdf_path is None
        assert result.error is None


class TestPrintingServiceNoPrinter:
    """When printer_type is 'none', thermal fails and falls back to PDF."""

    def test_no_printer_falls_back(self, sample_bill: BillData):
        """With no printer and no weasyprint, both methods fail gracefully."""
        service = PrintingService(printer_type="none")
        result = service.print_bill(sample_bill)
        # Thermal fails because printer_type='none'
        # PDF may fail if weasyprint not installed — either way no crash
        assert result.method in ("pdf", "failed")
        if result.method == "failed":
            assert "No thermal printer configured" in (result.error or "")

    def test_never_raises(self, sample_bill: BillData):
        """Service must never raise — fire-and-forget safe."""
        service = PrintingService(printer_type="none")
        # Should not raise regardless of environment
        result = service.print_bill(sample_bill)
        assert isinstance(result, BillResult)


class TestEscposPrinter:
    """Test escpos_printer module in isolation."""

    def test_no_printer_configured(self, sample_bill: BillData):
        from qorder_api.printing.escpos_printer import print_thermal

        result = print_thermal(
            sample_bill, printer_type="none", printer_ip=None, printer_port=9100
        )
        assert result.method == "failed"
        assert "No thermal printer configured" in (result.error or "")

    def test_unknown_printer_type(self, sample_bill: BillData):
        from qorder_api.printing.escpos_printer import print_thermal

        result = print_thermal(
            sample_bill, printer_type="bluetooth", printer_ip=None, printer_port=9100
        )
        # Will fail either because escpos not installed or unknown type
        assert result.method == "failed"
        assert result.error is not None

    def test_network_printer_no_ip(self, sample_bill: BillData):
        from qorder_api.printing.escpos_printer import print_thermal

        # Mock the escpos import so we can test the logic without the library
        with patch.dict("sys.modules", {"escpos": __import__("types").ModuleType("escpos"), "escpos.printer": __import__("types").ModuleType("escpos.printer")}):
            import sys
            sys.modules["escpos.printer"].Network = lambda *a, **kw: None  # type: ignore[attr-defined]
            sys.modules["escpos.printer"].Usb = lambda *a, **kw: None  # type: ignore[attr-defined]

            result = print_thermal(
                sample_bill, printer_type="network", printer_ip=None, printer_port=9100
            )
            assert result.method == "failed"
            assert "printer_ip is required" in (result.error or "")


class TestPdfPrinter:
    """Test pdf_printer module in isolation."""

    def test_weasyprint_not_installed(self, sample_bill: BillData):
        """When weasyprint is missing, returns failed with helpful error."""
        from qorder_api.printing.pdf_printer import print_pdf

        # If weasyprint is not installed, should return failed gracefully
        result = print_pdf(sample_bill, output_dir="/tmp/qorder_bills_test")
        # Either succeeds (weasyprint installed) or fails gracefully
        assert result.method in ("pdf", "failed")
        if result.method == "failed":
            assert "weasyprint" in (result.error or "").lower()

    def test_render_html(self, sample_bill: BillData):
        """HTML rendering should include all bill data."""
        from qorder_api.printing.pdf_printer import _render_html

        html = _render_html(sample_bill)
        assert "Quán Phở 24" in html
        assert "B3" in html
        assert "Phở bò tái" in html
        assert "Gỏi cuốn" in html
        assert "15/06/2024 14:30" in html


class TestFromSettings:
    """Test factory method from_settings."""

    def test_creates_service_from_settings(self):
        class FakeSettings:
            printer_type = "network"
            printer_ip = "10.0.0.50"
            printer_port = 9100
            bill_pdf_output_dir = "/var/bills"

        svc = PrintingService.from_settings(FakeSettings())
        assert svc._printer_type == "network"
        assert svc._printer_ip == "10.0.0.50"
        assert svc._printer_port == 9100
        assert svc._pdf_output_dir == "/var/bills"
