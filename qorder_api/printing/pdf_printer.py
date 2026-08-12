"""PDF bill generation fallback using WeasyPrint (R6.4).

When thermal printing is unavailable, this module renders the bill as a PDF
from an HTML template and saves it to disk.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

from qorder_api.printing.models import BillData, BillResult

logger = logging.getLogger(__name__)

_BILL_HTML_TEMPLATE = """\
<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="utf-8">
<style>
  body {{ font-family: 'Arial', sans-serif; width: 72mm; margin: 0 auto; padding: 8px; font-size: 12px; }}
  .center {{ text-align: center; }}
  .right {{ text-align: right; }}
  h1 {{ font-size: 16px; margin: 4px 0; }}
  .table-label {{ font-size: 14px; margin-bottom: 8px; }}
  hr {{ border: none; border-top: 1px dashed #000; margin: 6px 0; }}
  table {{ width: 100%; border-collapse: collapse; }}
  table td {{ padding: 2px 0; vertical-align: top; }}
  .item-name {{ font-weight: bold; }}
  .total {{ font-size: 14px; font-weight: bold; }}
  .timestamp {{ margin-top: 8px; font-size: 11px; color: #555; }}
</style>
</head>
<body>
  <div class="center">
    <h1>{restaurant_name}</h1>
    <div class="table-label">Bàn: {table_label}</div>
  </div>
  <hr>
  <table>
    {items_rows}
  </table>
  <hr>
  <div class="right total">TỔNG: {total}</div>
  <div class="center timestamp">{closed_at}</div>
</body>
</html>
"""


def _format_price(amount, currency: str) -> str:
    """Format a price value for display."""
    if currency == "VND":
        return f"{int(amount):,}đ".replace(",", ".")
    return f"{amount} {currency}"


def _render_html(bill: BillData) -> str:
    """Render bill data into an HTML string."""
    items_rows = ""
    for item in bill.items:
        line_total = _format_price(item.unit_price * item.quantity, bill.currency)
        items_rows += (
            f'<tr><td class="item-name">{item.name}</td>'
            f"<td>{item.quantity} x {_format_price(item.unit_price, bill.currency)}</td>"
            f"<td class=\"right\">{line_total}</td></tr>\n"
        )

    return _BILL_HTML_TEMPLATE.format(
        restaurant_name=bill.restaurant_name,
        table_label=bill.table_label,
        items_rows=items_rows,
        total=_format_price(bill.total_amount, bill.currency),
        closed_at=bill.closed_at.strftime("%d/%m/%Y %H:%M"),
    )


def print_pdf(bill: BillData, *, output_dir: str) -> BillResult:
    """Generate a PDF bill and save to output_dir.

    Parameters
    ----------
    bill : BillData
        The bill content to render.
    output_dir : str
        Directory to write the PDF file.

    Returns
    -------
    BillResult
        Result with method="pdf" and pdf_path on success, or method="failed".
    """
    try:
        from weasyprint import HTML  # type: ignore[import-untyped]
    except ImportError:
        return BillResult(
            method="failed",
            error="weasyprint is not installed. Install with: pip install 'qorder-api[printing]'",
        )

    try:
        # Ensure output directory exists
        Path(output_dir).mkdir(parents=True, exist_ok=True)

        # Generate filename from timestamp
        ts_str = bill.closed_at.strftime("%Y%m%d_%H%M%S")
        safe_table = bill.table_label.replace(" ", "_")
        filename = f"bill_{safe_table}_{ts_str}.pdf"
        pdf_path = os.path.join(output_dir, filename)

        # Render HTML and convert to PDF
        html_content = _render_html(bill)
        HTML(string=html_content).write_pdf(pdf_path)

        logger.info("Bill PDF generated: %s", pdf_path)
        return BillResult(method="pdf", pdf_path=pdf_path)

    except Exception as exc:  # noqa: BLE001
        logger.warning("PDF generation failed: %s", exc)
        return BillResult(method="failed", error=f"PDF generation error: {exc}")
