"""Tests for the layout-aware invoice extractor, against REAL generated PDFs.

These build actual PDF bytes with reportlab (an invoice like accounting software
emits), parse them through the real ingestion adapter, and assert the extractor
recovers the invoice from the table geometry — including the single-space-column
case that defeats the text-tier extractor, and the messy realities of unlabelled
currency and a letterhead vendor.
"""

from __future__ import annotations

from decimal import Decimal

import pytest

pytest.importorskip("reportlab")

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from clauseguard.adapters.extraction.layout_aware_invoice import (  # noqa: E402
    LayoutAwareInvoiceExtractor,
)
from clauseguard.adapters.ingestion.pdf_parser import NativePdfParser  # noqa: E402
from clauseguard.exceptions import InvoiceExtractionError  # noqa: E402


def _build_invoice_pdf(
    *,
    vendor_title: str = "ACME SUPPLIES PVT LTD",
    header_line: str = "Invoice No: INV-900 &nbsp; Date: 01/06/2026",
    rows: list[list[str]] | None = None,
) -> bytes:
    """Render a realistic invoice PDF and return its bytes."""
    import io

    rows = rows or [
        ["1", "WIDGET-A", "Standard widget", "150", "Rs 130.00", "Rs 19,500.00"],
        ["2", "GADGET-Z", "Mystery gadget", "5", "Rs 50.00", "Rs 250.00"],
    ]
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    header = ["#", "Item Code", "Description", "Qty", "Unit Price", "Amount"]
    table = Table([header, *rows])
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    doc.build(
        [
            Paragraph(vendor_title, styles["Title"]),
            Paragraph(header_line, styles["Normal"]),
            Spacer(1, 12),
            table,
        ]
    )
    return buf.getvalue()


def _extract(pdf_bytes: bytes):
    document = NativePdfParser().parse(pdf_bytes, source_ref="invoice.pdf")
    return LayoutAwareInvoiceExtractor().extract(document)


def test_extracts_from_real_pdf_geometry() -> None:
    invoice = _extract(_build_invoice_pdf())
    assert invoice.invoice_id == "INV-900"
    assert invoice.invoice_date.isoformat() == "2026-06-01"
    assert len(invoice.line_items) == 2
    assert invoice.line_items[0].description == "Standard widget"
    assert invoice.line_items[0].sku == "WIDGET-A"


def test_currency_inferred_from_amount_symbols() -> None:
    invoice = _extract(_build_invoice_pdf())
    assert invoice.currency == "INR"
    assert invoice.line_items[0].unit_rate.amount == Decimal("130.00")
    assert invoice.line_items[0].line_total.amount == Decimal("19500.00")


def test_vendor_falls_back_to_letterhead() -> None:
    invoice = _extract(_build_invoice_pdf(vendor_title="Globex Trading LLC"))
    assert invoice.vendor_name == "Globex Trading LLC"


def test_multi_field_header_line_is_split() -> None:
    invoice = _extract(
        _build_invoice_pdf(header_line="Invoice No: INV-777 &nbsp; Date: 15/03/2026")
    )
    assert invoice.invoice_id == "INV-777"
    assert invoice.invoice_date.isoformat() == "2026-03-15"


def test_missing_table_raises() -> None:
    import io

    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    doc.build([Paragraph("Just a letter, no table here.", styles["Normal"])])
    document = NativePdfParser().parse(buf.getvalue(), source_ref="letter.pdf")
    with pytest.raises(InvoiceExtractionError):
        LayoutAwareInvoiceExtractor().extract(document)
