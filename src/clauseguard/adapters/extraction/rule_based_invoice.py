"""Adapter: rule-based invoice extractor (Phase 2).

Turns the *text* of a structured invoice into a validated :class:`Invoice`
domain object — the missing middle link that lets a real document flow all the
way through the pipeline (``parse -> extract -> rules -> findings``).

This adapter is deterministic on purpose (no LLM), matching ClauseGuard's core
thesis: rigid, well-structured fields are parsed by explicit rules; only
genuinely ambiguous language is ever escalated to a model (a later phase). It
targets a **standardized text layout** so the pipeline can be made to work and
be fully tested first; a follow-up phase hardens the same port against the
messier text that real PDF extraction emits.

Expected text layout
---------------------
A header block of ``Key: value`` lines, then a pipe-delimited line-item table
whose first row names the columns::

    INVOICE
    Invoice-ID: INV-900
    Vendor: Acme Supplies Pvt Ltd
    Date: 2026-06-01
    Currency: INR

    Line | SKU | Description | Qty | Unit-Rate | Line-Total
    1 | WIDGET-A | Standard widget | 150 | 130.00 | 19500.00
    2 | GADGET-Z | Mystery gadget | 5 | 50.00 | 250.00

Design choices worth noting:

* **Column mapping is by header name, not fixed position** — reordering the
  columns does not break parsing.
* Header keys and column names are matched **case-insensitively** and tolerate
  surrounding whitespace, because real text extraction is rarely pixel-perfect.
* Monetary amounts are parsed as :class:`~decimal.Decimal` (never float) and
  stamped with the invoice-level currency.
* Every failure raises :class:`InvoiceExtractionError` with the offending line,
  so a malformed document fails loudly and traceably rather than silently
  producing a wrong :class:`Invoice`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from clauseguard.domain.models import Invoice, InvoiceLineItem, Money
from clauseguard.exceptions import InvoiceExtractionError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument

logger = get_logger(__name__)

# Header keys (lower-cased for case-insensitive lookup).
_KEY_INVOICE_ID = "invoice-id"
_KEY_VENDOR = "vendor"
_KEY_DATE = "date"
_KEY_CURRENCY = "currency"
_REQUIRED_HEADER_KEYS = (_KEY_INVOICE_ID, _KEY_VENDOR, _KEY_DATE, _KEY_CURRENCY)

# Line-item column names (lower-cased) -> canonical field.
_COL_LINE = "line"
_COL_SKU = "sku"
_COL_DESCRIPTION = "description"
_COL_QTY = "qty"
_COL_UNIT_RATE = "unit-rate"
_COL_LINE_TOTAL = "line-total"
_REQUIRED_COLUMNS = (
    _COL_LINE,
    _COL_SKU,
    _COL_DESCRIPTION,
    _COL_QTY,
    _COL_UNIT_RATE,
    _COL_LINE_TOTAL,
)

_TABLE_DELIMITER = "|"


class RuleBasedInvoiceExtractor:
    """Extract an :class:`Invoice` from standardized invoice text.

    Implements the :class:`~clauseguard.ports.extraction.InvoiceExtractor` port.
    """

    def extract(self, document: ParsedDocument) -> Invoice:
        """Parse ``document.text`` into a validated :class:`Invoice`.

        Args:
            document: The parsed invoice document (text + source ref).

        Returns:
            A populated, validated :class:`Invoice`.

        Raises:
            InvoiceExtractionError: If required header fields or line-item
                columns are missing, or any value cannot be parsed/validated.
        """
        lines = [ln.strip() for ln in document.text.splitlines() if ln.strip()]
        if not lines:
            raise InvoiceExtractionError(
                f"Document {document.source_ref} contains no text to extract"
            )

        header = self._parse_header(lines)
        currency = header[_KEY_CURRENCY].upper()
        line_items = self._parse_line_items(lines, currency)

        try:
            invoice = Invoice(
                invoice_id=header[_KEY_INVOICE_ID],
                vendor_name=header[_KEY_VENDOR],
                invoice_date=self._parse_date(header[_KEY_DATE]),
                currency=currency,
                line_items=tuple(line_items),
                source_ref=document.source_ref,
            )
        except ValueError as exc:
            # Pydantic validation (or date parsing) rejected the assembled data.
            raise InvoiceExtractionError(
                f"Invoice failed validation for {document.source_ref}: {exc}"
            ) from exc

        logger.info(
            "Invoice extracted",
            extra={
                "invoice_id": invoice.invoice_id,
                "line_items": len(invoice.line_items),
                "source_ref": document.source_ref,
            },
        )
        return invoice

    # ------------------------------------------------------------------ #
    # Header
    # ------------------------------------------------------------------ #
    def _parse_header(self, lines: list[str]) -> dict[str, str]:
        """Extract the ``Key: value`` header block.

        Args:
            lines: Non-empty, stripped document lines.

        Returns:
            A mapping of lower-cased header key -> value for the required keys.

        Raises:
            InvoiceExtractionError: If any required header key is missing.
        """
        header: dict[str, str] = {}
        for line in lines:
            if _TABLE_DELIMITER in line:
                continue  # table rows are not header lines
            if ":" not in line:
                continue
            key, _, value = line.partition(":")
            header[key.strip().lower()] = value.strip()

        missing = [k for k in _REQUIRED_HEADER_KEYS if not header.get(k)]
        if missing:
            raise InvoiceExtractionError(
                f"Missing required invoice header field(s): {', '.join(missing)}"
            )
        return header

    # ------------------------------------------------------------------ #
    # Line items
    # ------------------------------------------------------------------ #
    def _parse_line_items(
        self, lines: list[str], currency: str
    ) -> list[InvoiceLineItem]:
        """Parse the pipe-delimited line-item table.

        Args:
            lines: Non-empty, stripped document lines.
            currency: The invoice-level currency applied to all money fields.

        Returns:
            The parsed line items, in file order.

        Raises:
            InvoiceExtractionError: If the table header/columns are missing or a
                row cannot be parsed.
        """
        table_rows = [ln for ln in lines if _TABLE_DELIMITER in ln]
        if not table_rows:
            raise InvoiceExtractionError("No line-item table found in invoice text")

        column_index = self._build_column_index(table_rows[0])

        items: list[InvoiceLineItem] = []
        for row in table_rows[1:]:
            items.append(self._parse_row(row, column_index, currency))

        if not items:
            raise InvoiceExtractionError("Line-item table has a header but no rows")
        return items

    @staticmethod
    def _build_column_index(header_row: str) -> dict[str, int]:
        """Map each required column name to its position in the header row.

        Args:
            header_row: The first (column-naming) row of the table.

        Returns:
            A mapping of canonical column name -> cell index.

        Raises:
            InvoiceExtractionError: If any required column is absent.
        """
        cells = [c.strip().lower() for c in header_row.split(_TABLE_DELIMITER)]
        index = {name: pos for pos, name in enumerate(cells)}
        missing = [c for c in _REQUIRED_COLUMNS if c not in index]
        if missing:
            raise InvoiceExtractionError(
                f"Line-item table missing column(s): {', '.join(missing)}"
            )
        return index

    def _parse_row(
        self, row: str, column_index: dict[str, int], currency: str
    ) -> InvoiceLineItem:
        """Parse a single data row into an :class:`InvoiceLineItem`.

        Args:
            row: A pipe-delimited data row.
            column_index: Column-name -> position map from the header row.
            currency: Invoice-level currency for money fields.

        Returns:
            The parsed line item.

        Raises:
            InvoiceExtractionError: If a cell is missing or fails to parse.
        """
        cells = [c.strip() for c in row.split(_TABLE_DELIMITER)]
        expected = max(column_index.values()) + 1
        if len(cells) < expected:
            raise InvoiceExtractionError(
                f"Line-item row has {len(cells)} cells, expected at least "
                f"{expected}: {row!r}"
            )

        def cell(name: str) -> str:
            return cells[column_index[name]]

        try:
            return InvoiceLineItem(
                line_no=int(cell(_COL_LINE)),
                sku=cell(_COL_SKU),
                description=cell(_COL_DESCRIPTION),
                quantity=self._parse_decimal(cell(_COL_QTY)),
                unit_rate=Money(
                    amount=self._parse_decimal(cell(_COL_UNIT_RATE)),
                    currency=currency,
                ),
                line_total=Money(
                    amount=self._parse_decimal(cell(_COL_LINE_TOTAL)),
                    currency=currency,
                ),
            )
        except ValueError as exc:
            raise InvoiceExtractionError(
                f"Could not parse line-item row {row!r}: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Scalar parsers
    # ------------------------------------------------------------------ #
    @staticmethod
    def _parse_decimal(value: str) -> Decimal:
        """Parse a numeric string into a Decimal, stripping thousands commas.

        Args:
            value: The raw cell text (e.g. ``"19,500.00"``).

        Returns:
            The value as a :class:`~decimal.Decimal`.

        Raises:
            ValueError: If the text is not a valid number.
        """
        cleaned = value.replace(",", "").strip()
        try:
            return Decimal(cleaned)
        except InvalidOperation as exc:
            raise ValueError(f"invalid number {value!r}") from exc

    @staticmethod
    def _parse_date(value: str) -> date:
        """Parse an ISO ``YYYY-MM-DD`` date string.

        Args:
            value: The raw date text.

        Returns:
            The parsed :class:`~datetime.date`.

        Raises:
            ValueError: If the text is not an ISO date.
        """
        return date.fromisoformat(value.strip())