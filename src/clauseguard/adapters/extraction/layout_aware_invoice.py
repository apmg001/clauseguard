"""Adapter: layout-aware invoice extractor (Tier 2, industry-standard).

Reconstructs the line-item table from the PDF's *geometry* — the ruling lines /
word alignment recovered by the ingestion layer into ``ParsedDocument.tables`` —
instead of guessing at whitespace in flattened text. This is how real digital-PDF
invoice extraction is done (pdfplumber, Camelot, and the deterministic core of
tools like AWS Textract all work from layout, not string splitting), and it
handles the common case that defeats the text tier: columns separated only by
single spaces, where a description also contains spaces.

Real-world header handling
-------------------------
Real invoices rarely label the vendor or currency cleanly, so this extractor
applies documented, conservative fallbacks:

* **Currency** — an explicit ``Currency:`` field if present; otherwise inferred
  from the symbol/code on the amounts (``₹``/``Rs`` -> INR, ``$`` -> USD, ...).
* **Vendor** — an explicit ``Vendor:``/``Supplier:``/``From:`` field if present;
  otherwise the document's first non-empty line (the letterhead), a common and
  reasonable heuristic.

Header fields (invoice id, date) are parsed from the text, multi-field-aware, so
``Invoice No: INV-900   Date: 01/06/2026`` on one line is handled correctly.

Limits (the honest frontier): this needs the ingestion layer to have recovered a
table (true for digital PDFs with detectable structure). Scanned images need OCR
first; chaotic layouts that defeat table detection are the province of the LLM
extractor (Tier 4), which lives behind this same port.
"""

from __future__ import annotations

from clauseguard.adapters.extraction import _shared
from clauseguard.domain.models import Invoice, InvoiceLineItem, Money
from clauseguard.exceptions import InvoiceExtractionError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument

logger = get_logger(__name__)

_VENDOR_FALLBACK_KEY = "vendor"


class LayoutAwareInvoiceExtractor:
    """Extract an :class:`Invoice` from a document's recovered table geometry.

    Implements the :class:`~clauseguard.ports.extraction.InvoiceExtractor` port.
    """

    def extract(self, document: ParsedDocument) -> Invoice:
        """Parse a document's tables + header text into a validated Invoice.

        Args:
            document: The parsed document, including recovered ``tables``.

        Returns:
            A populated, validated :class:`Invoice`.

        Raises:
            InvoiceExtractionError: If no line-item table was recovered, required
                columns/fields are missing, or any value fails to parse/validate.
        """
        table = self._select_line_item_table(document.tables)
        if table is None:
            raise InvoiceExtractionError(
                f"No line-item table recovered from {document.source_ref}; "
                f"the document may be scanned (needs OCR) or have no detectable "
                f"table structure (needs the LLM extractor)"
            )

        header_row, *data_rows = table
        try:
            column_index = _shared.build_column_index(header_row)
        except ValueError as exc:
            raise InvoiceExtractionError(f"Line-item table {exc}") from exc
        if not data_rows:
            raise InvoiceExtractionError("Line-item table has a header but no rows")

        header = _shared.parse_header_fields(document.text)
        currency = self._resolve_currency(header, data_rows, column_index)
        vendor = self._resolve_vendor(header, document.text)

        for required in ("invoice_id", "date"):
            if required not in header:
                raise InvoiceExtractionError(
                    f"Missing required invoice header field: {required}"
                )

        line_items = [
            self._parse_row(row, column_index, currency) for row in data_rows
        ]

        try:
            invoice = Invoice(
                invoice_id=header["invoice_id"],
                vendor_name=vendor,
                invoice_date=_shared.parse_date(header["date"]),
                currency=currency,
                line_items=tuple(line_items),
                source_ref=document.source_ref,
            )
        except ValueError as exc:
            raise InvoiceExtractionError(
                f"Invoice failed validation for {document.source_ref}: {exc}"
            ) from exc

        logger.info(
            "Invoice extracted (layout-aware)",
            extra={"invoice_id": invoice.invoice_id,
                   "line_items": len(invoice.line_items),
                   "source_ref": document.source_ref},
        )
        return invoice

    @staticmethod
    def _select_line_item_table(
        tables: list[list[list[str]]],
    ) -> list[list[str]] | None:
        """Return the first recovered table whose header names >= 3 columns."""
        for table in tables:
            if table and _shared.count_column_matches(table[0]) >= 3:
                return table
        return None

    @staticmethod
    def _resolve_currency(
        header: dict[str, str],
        data_rows: list[list[str]],
        column_index: dict[str, int],
    ) -> str:
        """Resolve the currency: explicit field, else inferred from amounts.

        Raises:
            InvoiceExtractionError: If currency is neither labelled nor inferable.
        """
        if "currency" in header:
            return header["currency"].upper()

        rate_col = column_index["unit_rate"]
        total_col = column_index["line_total"]
        sample = " ".join(
            row[c]
            for row in data_rows
            for c in (rate_col, total_col)
            if c < len(row)
        )
        inferred = _shared.detect_currency(sample)
        if inferred:
            return inferred
        raise InvoiceExtractionError(
            "Currency is neither labelled nor inferable from the amounts"
        )

    @staticmethod
    def _resolve_vendor(header: dict[str, str], text: str) -> str:
        """Resolve the vendor: explicit field, else the letterhead (first line).

        Raises:
            InvoiceExtractionError: If no vendor can be determined.
        """
        if _VENDOR_FALLBACK_KEY in header:
            return header[_VENDOR_FALLBACK_KEY]
        for line in text.splitlines():
            if line.strip():
                return line.strip()
        raise InvoiceExtractionError("Could not determine the vendor")

    @staticmethod
    def _parse_row(
        row: list[str], column_index: dict[str, int], currency: str
    ) -> InvoiceLineItem:
        """Parse one recovered table row into an :class:`InvoiceLineItem`."""
        needed = max(column_index.values()) + 1
        if len(row) < needed:
            raise InvoiceExtractionError(
                f"Line-item row has {len(row)} cells, expected at least "
                f"{needed}: {row!r}"
            )

        def cell(name: str) -> str:
            return row[column_index[name]]

        try:
            return InvoiceLineItem(
                line_no=int(cell("line")),
                sku=cell("sku"),
                description=cell("description"),
                quantity=_shared.parse_amount(cell("qty")),
                unit_rate=Money(amount=_shared.parse_amount(cell("unit_rate")),
                                currency=currency),
                line_total=Money(amount=_shared.parse_amount(cell("line_total")),
                                 currency=currency),
            )
        except ValueError as exc:
            raise InvoiceExtractionError(
                f"Could not parse line-item row {row!r}: {exc}"
            ) from exc
