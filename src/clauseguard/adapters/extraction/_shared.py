"""Shared extraction primitives.

Single source of truth for the label aliases and field parsers used by every
invoice extractor (text-based and layout-aware), so the vocabulary of "what a
column/header can be called" and "how a money/date value is parsed" lives in one
place. Keeping this here is what lets a second extractor reuse the first's
hard-won parsing rules instead of duplicating them.
"""

from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation

HEADER_ALIASES: dict[str, frozenset[str]] = {
    "invoice_id": frozenset(
        {"invoice-id", "invoice id", "invoice no", "invoice no.", "invoice number",
         "invoice #", "inv no", "inv no.", "inv #", "invoice"}
    ),
    "vendor": frozenset(
        {"vendor", "vendor name", "supplier", "supplier name", "seller", "from",
         "billed by"}
    ),
    "date": frozenset(
        {"date", "invoice date", "dated", "issue date", "date of issue"}
    ),
    "currency": frozenset({"currency", "curr", "ccy"}),
}

COLUMN_ALIASES: dict[str, frozenset[str]] = {
    "line": frozenset({"line", "line no", "line #", "sr", "sr no", "s.no",
                       "sl no", "#"}),
    "sku": frozenset({"sku", "item", "item code", "item no", "code", "product",
                      "product code", "part no", "part number"}),
    "description": frozenset({"description", "desc", "details",
                              "item description", "particulars"}),
    "qty": frozenset({"qty", "quantity", "units", "qnty"}),
    "unit_rate": frozenset({"unit-rate", "unit rate", "unit price", "rate",
                            "price", "unit cost"}),
    "line_total": frozenset({"line-total", "line total", "amount", "total",
                             "line amount", "net amount"}),
}

HEADER_LABEL_TO_CANON = {
    label: canon for canon, labels in HEADER_ALIASES.items() for label in labels
}
COLUMN_LABEL_TO_CANON = {
    label: canon for canon, labels in COLUMN_ALIASES.items() for label in labels
}

REQUIRED_HEADER = ("invoice_id", "vendor", "date", "currency")
REQUIRED_COLUMNS = ("line", "sku", "description", "qty", "unit_rate", "line_total")

_CURRENCY_SYMBOLS = ("₹", "$", "€", "£", "¥")
_CURRENCY_CODE_RE = re.compile(r"(?i)\b(rs|inr|usd|eur|gbp|jpy)\b\.?")

_CURRENCY_FROM_TOKEN = [
    ("₹", "INR"), ("rs", "INR"), ("inr", "INR"),
    ("$", "USD"), ("usd", "USD"),
    ("€", "EUR"), ("eur", "EUR"),
    ("£", "GBP"), ("gbp", "GBP"),
    ("¥", "JPY"), ("jpy", "JPY"),
]

_DATE_FORMATS = ("%d/%m/%Y", "%d-%m-%Y", "%d %b %Y", "%d %B %Y",
                 "%b %d, %Y", "%B %d, %Y")


def parse_amount(value: str) -> Decimal:
    """Parse a monetary/quantity string into a Decimal.

    Strips known currency symbols/codes and thousands separators, but NOT
    arbitrary letters — so genuine junk (e.g. an OCR ``1O0.00``) raises rather
    than being silently coerced into a wrong number.

    Args:
        value: Raw cell text.

    Returns:
        The value as a :class:`~decimal.Decimal`.

    Raises:
        ValueError: If the cleaned text is not a valid number.
    """
    cleaned = value.strip()
    for sym in _CURRENCY_SYMBOLS:
        cleaned = cleaned.replace(sym, "")
    cleaned = _CURRENCY_CODE_RE.sub("", cleaned)
    cleaned = cleaned.replace(",", "").strip()
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"invalid number {value!r}") from exc


def parse_date(value: str) -> date:
    """Parse a date, trying ISO first then common fallback formats.

    Day-first is assumed for ambiguous numeric formats (common outside the US).

    Args:
        value: Raw date text.

    Returns:
        The parsed :class:`~datetime.date`.

    Raises:
        ValueError: If no supported format matches.
    """
    text = value.strip()
    try:
        return date.fromisoformat(text)
    except ValueError:
        pass
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(f"unrecognised date format {value!r}")


def detect_currency(sample_text: str) -> str | None:
    """Infer an ISO currency from symbols/codes in text, or None.

    Args:
        sample_text: Text to scan (e.g. concatenated amount cells).

    Returns:
        A 3-letter ISO code, or None if nothing recognisable is present.
    """
    low = sample_text.lower()
    for token, iso in _CURRENCY_FROM_TOKEN:
        if token in low:
            return iso
    return None


_HEADER_LABEL_RE = re.compile(
    r"(?i)(?<![\w-])(" + "|".join(
        re.escape(lbl) for lbl in sorted(HEADER_LABEL_TO_CANON, key=len, reverse=True)
    ) + r")\s*:",
)


def parse_header_fields(text: str) -> dict[str, str]:
    """Extract canonical header fields from free text (multi-field aware).

    Handles several ``Label: value`` pairs on one line by locating each known
    label and taking the text up to the next label as its value. Unknown labels
    are ignored. No field is required here — the caller decides.

    Args:
        text: The header text block (everything above the line-item table).

    Returns:
        A mapping of canonical header field -> value for whatever was found.
    """
    found: dict[str, str] = {}
    for line in text.splitlines():
        matches = list(_HEADER_LABEL_RE.finditer(line))
        for i, m in enumerate(matches):
            canon = HEADER_LABEL_TO_CANON[m.group(1).strip().lower()]
            start = m.end()
            end = matches[i + 1].start() if i + 1 < len(matches) else len(line)
            value = line[start:end].strip()
            if value and canon not in found:
                found[canon] = value
    return found


def build_column_index(header_cells: list[str]) -> dict[str, int]:
    """Map each required canonical column to its position, resolving aliases.

    Args:
        header_cells: The already-split cells of the table's header row.

    Returns:
        A mapping of canonical column -> cell index.

    Raises:
        ValueError: If any required column is absent.
    """
    index: dict[str, int] = {}
    for pos, cell in enumerate(header_cells):
        canon = COLUMN_LABEL_TO_CANON.get(cell.strip().lower())
        if canon and canon not in index:
            index[canon] = pos
    missing = [c for c in REQUIRED_COLUMNS if c not in index]
    if missing:
        raise ValueError(f"missing column(s): {', '.join(missing)}")
    return index


def count_column_matches(cells: list[str]) -> int:
    """Return how many cells look like known column names (table-header test)."""
    return sum(1 for c in cells if c.strip().lower() in COLUMN_LABEL_TO_CANON)
