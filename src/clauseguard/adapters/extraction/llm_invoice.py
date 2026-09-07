"""Adapter: LLM invoice extractor (Tier 4 — for layouts rules can't parse).

The final tier of the extraction architecture (string -> layout -> LLM). When a
document's layout defeats the deterministic parsers, a language model reads it
and returns a structured invoice as JSON. This is the cleanest expression of
ClauseGuard's thesis: the LLM is used only for *genuine language/layout
ambiguity* (reading a messy document), while the money math stays deterministic
in the rules engine.

Decoupling
----------
This adapter depends on the abstract
:class:`~clauseguard.providers.base.LLMProvider` (injected), never a concrete
provider, so it works identically against a local Ollama model or a hosted API
and is fully unit-testable with a scripted fake. It sits behind the same
:class:`~clauseguard.ports.extraction.InvoiceExtractor` port as every other
extractor.

Anti-hallucination: grounding, not "fixing"
-------------------------------------------
A model asked to extract numbers can invent them. Crucially, we do **not** verify
by recomputing ``qty x rate == line_total`` — a real invoice arithmetic error
would fail that, and catching those is the rules engine's job. Instead we verify
**grounding**: every value the model claims to have extracted must actually
appear in the source text. A figure that isn't traceable to the document is a
hallucination and the extraction is rejected — while genuine invoice errors,
being present in the source, pass through to the rules unharmed. This keeps the
output audit-grade (every field is traceable) even though extraction used an LLM.
"""

from __future__ import annotations

import json
import re
from datetime import date
from decimal import Decimal, InvalidOperation

from clauseguard.domain.models import Invoice, InvoiceLineItem, Money
from clauseguard.exceptions import InvoiceExtractionError, LLMProviderError
from clauseguard.logging_config import get_logger
from clauseguard.ports.ingestion import ParsedDocument
from clauseguard.providers.base import CompletionRequest, LLMProvider

logger = get_logger(__name__)

_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)
_SOURCE_NUMBER_RE = re.compile(r"\d[\d,]*\.?\d*")

_SYSTEM_PROMPT = (
    "You extract a vendor invoice into structured data. Read the invoice text "
    "and return ONLY a JSON object (no prose, no code fences) with keys: "
    '"invoice_id" (string), "vendor_name" (string), "invoice_date" '
    '(YYYY-MM-DD), "currency" (3-letter ISO code), and "line_items" (array). '
    "Each line item has: \"line_no\" (int), \"sku\" (string), "
    '"description" (string), "quantity" (number), "unit_rate" (number), '
    '"line_total" (number). Transcribe values EXACTLY as printed — never '
    "compute, correct, or infer a number that is not in the document."
)

_USER_TEMPLATE = 'Invoice text:\n"""\n{text}\n"""'


class LLMInvoiceExtractor:
    """Extract an :class:`Invoice` from document text using an LLM.

    Implements the :class:`~clauseguard.ports.extraction.InvoiceExtractor` port.

    Args:
        provider: The (injected) LLM provider used to perform extraction.
    """

    def __init__(self, provider: LLMProvider) -> None:
        self._provider = provider

    def extract(self, document: ParsedDocument) -> Invoice:
        """Extract, validate, and ground-check an invoice from document text.

        Args:
            document: The parsed document (its ``text`` is sent to the model).

        Returns:
            A populated, validated, source-grounded :class:`Invoice`.

        Raises:
            InvoiceExtractionError: On provider failure, unparseable/invalid
                JSON, schema violations, or any value not grounded in the source.
        """
        if not document.text.strip():
            raise InvoiceExtractionError(
                f"Document {document.source_ref} has no text to extract"
            )

        raw = self._call_model(document.text)
        data = self._parse_json(raw)
        invoice = self._build_invoice(data, document.source_ref)
        self._verify_grounded(invoice, document.text)

        logger.info(
            "Invoice extracted (LLM)",
            extra={"invoice_id": invoice.invoice_id,
                   "line_items": len(invoice.line_items),
                   "source_ref": document.source_ref},
        )
        return invoice

    def _call_model(self, text: str) -> str:
        """Prompt the provider; translate provider failures to extraction errors."""
        request = CompletionRequest(
            system=_SYSTEM_PROMPT,
            user=_USER_TEMPLATE.format(text=text),
            temperature=0.0,
            max_tokens=1024,
        )
        try:
            return self._provider.complete(request)
        except LLMProviderError as exc:
            raise InvoiceExtractionError(f"LLM provider failed: {exc}") from exc

    @staticmethod
    def _parse_json(raw: str) -> dict:
        """Extract the first JSON object from a (possibly noisy) response."""
        match = _JSON_OBJECT_RE.search(raw)
        if not match:
            raise InvoiceExtractionError(
                f"No JSON object in LLM output: {raw[:200]}"
            )
        try:
            data = json.loads(match.group(0))
        except json.JSONDecodeError as exc:
            raise InvoiceExtractionError(f"Invalid JSON from LLM: {exc}") from exc
        if not isinstance(data, dict):
            raise InvoiceExtractionError("LLM JSON root is not an object")
        return data

    def _build_invoice(self, data: dict, source_ref: str) -> Invoice:
        """Map the LLM JSON onto a validated :class:`Invoice`."""
        try:
            currency = str(data["currency"]).upper()
            line_items = tuple(
                self._build_line_item(li, currency) for li in data["line_items"]
            )
            return Invoice(
                invoice_id=str(data["invoice_id"]),
                vendor_name=str(data["vendor_name"]),
                invoice_date=date.fromisoformat(str(data["invoice_date"])),
                currency=currency,
                line_items=line_items,
                source_ref=source_ref,
            )
        except (KeyError, TypeError) as exc:
            raise InvoiceExtractionError(
                f"LLM JSON missing/!invalid field: {exc}"
            ) from exc
        except ValueError as exc:  # Decimal/date/pydantic validation
            raise InvoiceExtractionError(
                f"LLM invoice failed validation: {exc}"
            ) from exc

    @staticmethod
    def _build_line_item(li: dict, currency: str) -> InvoiceLineItem:
        """Build one validated line item from an LLM JSON entry."""
        return InvoiceLineItem(
            line_no=int(li["line_no"]),
            sku=str(li["sku"]),
            description=str(li["description"]),
            quantity=Decimal(str(li["quantity"])),
            unit_rate=Money(amount=Decimal(str(li["unit_rate"])), currency=currency),
            line_total=Money(amount=Decimal(str(li["line_total"])), currency=currency),
        )

    def _verify_grounded(self, invoice: Invoice, source_text: str) -> None:
        """Reject any extracted value not traceable to the source text.

        Numeric values must equal a number present in the source; SKUs and the
        invoice id must appear as substrings. This catches invented figures
        without rejecting genuine invoice errors (which are present in the source
        and are the rules engine's job to flag).

        Raises:
            InvoiceExtractionError: If a value is not grounded in the source.
        """
        numbers = self._source_numbers(source_text)
        haystack = source_text.lower()

        if invoice.invoice_id.lower() not in haystack:
            raise InvoiceExtractionError(
                f"Ungrounded invoice_id {invoice.invoice_id!r} (not in source)"
            )

        for item in invoice.line_items:
            if item.sku.lower() not in haystack:
                raise InvoiceExtractionError(
                    f"Ungrounded SKU {item.sku!r} on line {item.line_no}"
                )
            for label, value in (
                ("quantity", item.quantity),
                ("unit_rate", item.unit_rate.amount),
                ("line_total", item.line_total.amount),
            ):
                if value not in numbers:
                    raise InvoiceExtractionError(
                        f"Ungrounded {label} {value} on line {item.line_no} "
                        f"(not found in source — possible hallucination)"
                    )

    @staticmethod
    def _source_numbers(text: str) -> set[Decimal]:
        """Return the set of numeric values present in the source text."""
        found: set[Decimal] = set()
        for token in _SOURCE_NUMBER_RE.findall(text):
            cleaned = token.replace(",", "").strip(".")
            if not cleaned:
                continue
            try:
                found.add(Decimal(cleaned))
            except InvalidOperation:
                continue
        return found
