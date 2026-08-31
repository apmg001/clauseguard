"""Adapter: rule-based contract extractor (Phase 2).

Turns the *text* of a structured contract into a validated :class:`Contract`
domain object, the counterpart to :class:`RuleBasedInvoiceExtractor`. With both
in place, an entire reconciliation can be driven from documents (text) rather
than hand-built objects.

Deterministic on purpose (no LLM), matching ClauseGuard's thesis: rigid,
well-structured fields are parsed by explicit rules. It targets a standardized
text layout so the pipeline works and is fully tested first; hardening against
messier real-world PDF text is a later phase behind this same port.

Expected text layout
--------------------
A header block of ``Key: value`` lines, then a pipe-delimited rate-card table
whose first row names the columns. Volume discounts are encoded in one cell as
``min_qty:pct`` pairs separated by ``;`` (an empty cell means no discounts)::

    CONTRACT
    Contract-ID: C-001
    Vendor: Acme Supplies Pvt Ltd
    Valid-From: 2026-01-01
    Valid-To: 2026-12-31
    Currency: INR

    SKU | Description | Unit-Rate | Volume-Discounts
    WIDGET-A | Standard widget | 100.00 | 100:0.10; 500:0.15
    GADGET-Y | Fancy gadget | 50.00 |

Design choices mirror the invoice extractor: column mapping is by header name
(not position), keys/columns are matched case-insensitively, money is parsed as
:class:`~decimal.Decimal`, and any unparseable field raises
:class:`ContractExtractionError` with the offending line rather than silently
producing a wrong :class:`Contract`.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from clauseguard.domain.models import (
    Contract,
    Money,
    RateCardEntry,
    VolumeDiscountTier,
)
from clauseguard.exceptions import ContractExtractionError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument

logger = get_logger(__name__)

# Header keys (lower-cased for case-insensitive lookup).
_KEY_CONTRACT_ID = "contract-id"
_KEY_VENDOR = "vendor"
_KEY_VALID_FROM = "valid-from"
_KEY_VALID_TO = "valid-to"
_KEY_CURRENCY = "currency"
_REQUIRED_HEADER_KEYS = (
    _KEY_CONTRACT_ID,
    _KEY_VENDOR,
    _KEY_VALID_FROM,
    _KEY_VALID_TO,
    _KEY_CURRENCY,
)

# Rate-card column names (lower-cased) -> canonical field.
_COL_SKU = "sku"
_COL_DESCRIPTION = "description"
_COL_UNIT_RATE = "unit-rate"
_COL_VOLUME_DISCOUNTS = "volume-discounts"
_REQUIRED_COLUMNS = (_COL_SKU, _COL_DESCRIPTION, _COL_UNIT_RATE)  # discounts optional

_TABLE_DELIMITER = "|"
_TIER_SEPARATOR = ";"
_TIER_KV = ":"


class RuleBasedContractExtractor:
    """Extract a :class:`Contract` from standardized contract text.

    Implements the :class:`~clauseguard.ports.extraction.ContractExtractor` port.
    """

    def extract(self, document: ParsedDocument) -> Contract:
        """Parse ``document.text`` into a validated :class:`Contract`.

        Args:
            document: The parsed contract document (text + source ref).

        Returns:
            A populated, validated :class:`Contract`.

        Raises:
            ContractExtractionError: If required header fields or rate-card
                columns are missing, or any value cannot be parsed/validated.
        """
        lines = [ln.strip() for ln in document.text.splitlines() if ln.strip()]
        if not lines:
            raise ContractExtractionError(
                f"Document {document.source_ref} contains no text to extract"
            )

        header = self._parse_header(lines)
        currency = header[_KEY_CURRENCY].upper()
        rate_cards = self._parse_rate_cards(lines, currency)

        try:
            contract = Contract(
                contract_id=header[_KEY_CONTRACT_ID],
                vendor_name=header[_KEY_VENDOR],
                valid_from=self._parse_date(header[_KEY_VALID_FROM]),
                valid_to=self._parse_date(header[_KEY_VALID_TO]),
                currency=currency,
                rate_cards=tuple(rate_cards),
                source_ref=document.source_ref,
            )
        except ValueError as exc:
            # Pydantic validation, date parsing, or the validity-window check.
            raise ContractExtractionError(
                f"Contract failed validation for {document.source_ref}: {exc}"
            ) from exc

        logger.info(
            "Contract extracted",
            extra={
                "contract_id": contract.contract_id,
                "rate_cards": len(contract.rate_cards),
                "source_ref": document.source_ref,
            },
        )
        return contract

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
            ContractExtractionError: If any required header key is missing.
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
            raise ContractExtractionError(
                f"Missing required contract header field(s): {', '.join(missing)}"
            )
        return header

    # ------------------------------------------------------------------ #
    # Rate cards
    # ------------------------------------------------------------------ #
    def _parse_rate_cards(
        self, lines: list[str], currency: str
    ) -> list[RateCardEntry]:
        """Parse the pipe-delimited rate-card table.

        Args:
            lines: Non-empty, stripped document lines.
            currency: The contract-level currency applied to all rates.

        Returns:
            The parsed rate-card entries, in file order.

        Raises:
            ContractExtractionError: If the table header/columns are missing or a
                row cannot be parsed.
        """
        table_rows = [ln for ln in lines if _TABLE_DELIMITER in ln]
        if not table_rows:
            raise ContractExtractionError("No rate-card table found in contract text")

        column_index = self._build_column_index(table_rows[0])

        entries: list[RateCardEntry] = []
        for row in table_rows[1:]:
            entries.append(self._parse_row(row, column_index, currency))

        if not entries:
            raise ContractExtractionError("Rate-card table has a header but no rows")
        return entries

    @staticmethod
    def _build_column_index(header_row: str) -> dict[str, int]:
        """Map each required column name to its position in the header row.

        Args:
            header_row: The first (column-naming) row of the table.

        Returns:
            A mapping of column name -> cell index (includes optional columns
            when present).

        Raises:
            ContractExtractionError: If any required column is absent.
        """
        cells = [c.strip().lower() for c in header_row.split(_TABLE_DELIMITER)]
        index = {name: pos for pos, name in enumerate(cells)}
        missing = [c for c in _REQUIRED_COLUMNS if c not in index]
        if missing:
            raise ContractExtractionError(
                f"Rate-card table missing column(s): {', '.join(missing)}"
            )
        return index

    def _parse_row(
        self, row: str, column_index: dict[str, int], currency: str
    ) -> RateCardEntry:
        """Parse a single rate-card row into a :class:`RateCardEntry`.

        Args:
            row: A pipe-delimited data row.
            column_index: Column-name -> position map from the header row.
            currency: Contract-level currency for the unit rate.

        Returns:
            The parsed rate-card entry.

        Raises:
            ContractExtractionError: If a required cell is missing or fails to
                parse/validate.
        """
        cells = [c.strip() for c in row.split(_TABLE_DELIMITER)]
        required_width = max(column_index[c] for c in _REQUIRED_COLUMNS) + 1
        if len(cells) < required_width:
            raise ContractExtractionError(
                f"Rate-card row has {len(cells)} cells, expected at least "
                f"{required_width}: {row!r}"
            )

        def cell(name: str) -> str:
            pos = column_index.get(name)
            if pos is None or pos >= len(cells):
                return ""
            return cells[pos]

        try:
            return RateCardEntry(
                sku=cell(_COL_SKU),
                description=cell(_COL_DESCRIPTION),
                unit_rate=Money(
                    amount=self._parse_decimal(cell(_COL_UNIT_RATE)),
                    currency=currency,
                ),
                volume_discounts=self._parse_discounts(cell(_COL_VOLUME_DISCOUNTS)),
            )
        except ValueError as exc:
            raise ContractExtractionError(
                f"Could not parse rate-card row {row!r}: {exc}"
            ) from exc

    # ------------------------------------------------------------------ #
    # Field parsers
    # ------------------------------------------------------------------ #
    def _parse_discounts(self, cell: str) -> tuple[VolumeDiscountTier, ...]:
        """Parse a volume-discount cell (``"100:0.10; 500:0.15"``).

        Args:
            cell: The raw cell text; empty means no discounts.

        Returns:
            The parsed discount tiers (possibly empty).

        Raises:
            ValueError: If a tier is malformed or its values are out of range.
        """
        cell = cell.strip()
        if not cell:
            return ()
        tiers: list[VolumeDiscountTier] = []
        for pair in cell.split(_TIER_SEPARATOR):
            pair = pair.strip()
            if not pair:
                continue
            if _TIER_KV not in pair:
                raise ValueError(f"malformed discount tier {pair!r} (want qty:pct)")
            qty_s, _, pct_s = pair.partition(_TIER_KV)
            tiers.append(
                VolumeDiscountTier(
                    min_quantity=self._parse_decimal(qty_s),
                    discount_pct=self._parse_decimal(pct_s),
                )
            )
        return tuple(tiers)

    @staticmethod
    def _parse_decimal(value: str) -> Decimal:
        """Parse a numeric string into a Decimal, stripping thousands commas.

        Args:
            value: The raw cell text (e.g. ``"1,000.00"``).

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