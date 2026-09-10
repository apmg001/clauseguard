"""Adapter: rule-based invoice extractor (text tier).

Parses *semi-structured invoice text* (pipe / tab / multi-space delimited
tables, aliased header labels, currency-formatted amounts) into a validated
:class:`Invoice`. Deterministic by design — no LLM.

This is the **text tier**: it works when a delimiter reliably separates columns.
For real digital PDFs where columns are single-space-aligned (no delimiter), use
:class:`~clauseguard.adapters.extraction.layout_aware_invoice.LayoutAwareInvoiceExtractor`,
which reconstructs the table from the PDF's geometry instead of guessing at
whitespace. Both share the parsing vocabulary in
:mod:`clauseguard.adapters.extraction._shared`.
"""

from __future__ import annotations

import re

from clauseguard.adapters.extraction import _shared
from clauseguard.domain.models import Invoice, InvoiceLineItem, Money
from clauseguard.exceptions import InvoiceExtractionError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument

logger = get_logger(__name__)

_ROW_SPLIT_RE = re.compile(r"\s{2,}|\t")  # 2+ spaces or a tab


class RuleBasedInvoiceExtractor:
    """Extract an :class:`Invoice` from delimited invoice text.

    Implements the :class:`~clauseguard.ports.extraction.InvoiceExtractor` port.
    """

    def extract(self, document: ParsedDocument) -> Invoice:
        """Parse ``document.text`` into a validated :class:`Invoice`.

        Args:
            document: The parsed invoice document (text + source ref).

        Returns:
            A populated, validated :class:`Invoice`.

        Raises:
            InvoiceExtractionError: If the line-item table or required header
                fields cannot be located, or any value fails to parse/validate.
        """
        lines = [ln.strip() for ln in document.text.splitlines() if ln.strip()]
        if not lines:
            raise InvoiceExtractionError(
                f"Document {document.source_ref} contains no text to extract"
            )

        header_idx = self._find_table_header(lines)
        header = _shared.parse_header_fields("\n".join(lines[:header_idx]))
        missing = [k for k in _shared.REQUIRED_HEADER if k not in header]
        if missing:
            raise InvoiceExtractionError(
                f"Missing required invoice header field(s): {', '.join(missing)}"
            )

        currency = header["currency"].upper()
        try:
            column_index = _shared.build_column_index(
                self._split_row(lines[header_idx])
            )
        except ValueError as exc:
            raise InvoiceExtractionError(f"Line-item table {exc}") from exc

        line_items = self._parse_rows(lines[header_idx + 1:], column_index, currency)

        try:
            invoice = Invoice(
                invoice_id=header["invoice_id"],
                vendor_name=header["vendor"],
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
            "Invoice extracted (text tier)",
            extra={"invoice_id": invoice.invoice_id,
                   "line_items": len(invoice.line_items),
                   "source_ref": document.source_ref},
        )
        return invoice

    def _find_table_header(self, lines: list[str]) -> int:
        """Return the index of the column-header row (>= 3 known column names)."""
        for idx, line in enumerate(lines):
            if _shared.count_column_matches(self._split_row(line)) >= 3:
                return idx
        raise InvoiceExtractionError("No line-item table header found in invoice text")

    @staticmethod
    def _split_row(row: str) -> list[str]:
        """Split a row into cells by pipe, else by tab / 2-or-more spaces."""
        if "|" in row:
            return [c.strip() for c in row.split("|")]
        return [c.strip() for c in _ROW_SPLIT_RE.split(row.strip())]

    def _parse_rows(
        self, rows: list[str], column_index: dict[str, int], currency: str
    ) -> list[InvoiceLineItem]:
        """Parse data rows into line items."""
        items = [self._parse_row(r, column_index, currency) for r in rows]
        if not items:
            raise InvoiceExtractionError("Line-item table has a header but no rows")
        return items

    def _parse_row(
        self, row: str, column_index: dict[str, int], currency: str
    ) -> InvoiceLineItem:
        """Parse one data row into an :class:`InvoiceLineItem`."""
        cells = self._split_row(row)
        needed = max(column_index.values()) + 1
        if len(cells) < needed:
            raise InvoiceExtractionError(
                f"Line-item row has {len(cells)} cells, expected at least "
                f"{needed}: {row!r}"
            )

        def cell(name: str) -> str:
            return cells[column_index[name]]

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
