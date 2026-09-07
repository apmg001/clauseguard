"""Tests for the LLM invoice extractor and the provider retry policy.

All offline: a scripted fake provider stands in for a real model, so the
extraction logic, JSON handling, grounding-based anti-hallucination, and the
provider's transient-retry behaviour are all verified with zero network.
"""

from __future__ import annotations

import json
from datetime import date
from decimal import Decimal

import pytest

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.extraction.llm_invoice import LLMInvoiceExtractor
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.domain.enums import DiscrepancyType
from clauseguard.domain.models import (
    Contract,
    Money,
    RateCardEntry,
    VolumeDiscountTier,
)
from clauseguard.exceptions import (
    InvoiceExtractionError,
    PermanentLLMError,
    TransientLLMError,
)
from clauseguard.ports.ingestion import ParsedDocument
from clauseguard.providers.base import CompletionRequest, LLMProvider
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService

SOURCE_TEXT = """\
ACME SUPPLIES PVT LTD
Invoice No: INV-900   Date: 01/06/2026
1  WIDGET-A  Standard widget  150  Rs 130.00  Rs 19,500.00
"""

GOOD_JSON = json.dumps(
    {
        "invoice_id": "INV-900",
        "vendor_name": "Acme Supplies Pvt Ltd",
        "invoice_date": "2026-06-01",
        "currency": "INR",
        "line_items": [
            {"line_no": 1, "sku": "WIDGET-A", "description": "Standard widget",
             "quantity": "150", "unit_rate": "130.00", "line_total": "19500.00"},
        ],
    }
)


class ScriptedProvider(LLMProvider):
    """Return a fixed response string (no network)."""

    def __init__(self, response: str) -> None:
        super().__init__(model="fake", timeout_seconds=1.0, max_retries=0,
                         retry_backoff_base=0.0)
        self._response = response

    def _raw_complete(self, request: CompletionRequest) -> str:
        return self._response

    def close(self) -> None:
        return None


def _doc(text: str = SOURCE_TEXT) -> ParsedDocument:
    return ParsedDocument(text=text, page_count=1, source_ref="invoice.pdf")


def test_extracts_valid_json() -> None:
    invoice = LLMInvoiceExtractor(ScriptedProvider(GOOD_JSON)).extract(_doc())
    assert invoice.invoice_id == "INV-900"
    assert invoice.currency == "INR"
    assert len(invoice.line_items) == 1
    assert invoice.line_items[0].unit_rate.amount == Decimal("130.00")


def test_tolerates_prose_and_code_fences() -> None:
    noisy = f"Sure, here you go:\n```json\n{GOOD_JSON}\n```"
    invoice = LLMInvoiceExtractor(ScriptedProvider(noisy)).extract(_doc())
    assert invoice.invoice_id == "INV-900"


def test_malformed_json_raises() -> None:
    with pytest.raises(InvoiceExtractionError):
        LLMInvoiceExtractor(ScriptedProvider("I couldn't read it.")).extract(_doc())


def test_missing_field_raises() -> None:
    bad = json.dumps({"invoice_id": "INV-900", "currency": "INR"})
    with pytest.raises(InvoiceExtractionError):
        LLMInvoiceExtractor(ScriptedProvider(bad)).extract(_doc())


def test_ungrounded_amount_is_rejected() -> None:
    hallucinated = json.dumps(
        {
            "invoice_id": "INV-900", "vendor_name": "Acme",
            "invoice_date": "2026-06-01", "currency": "INR",
            "line_items": [
                {"line_no": 1, "sku": "WIDGET-A", "description": "Standard widget",
                 "quantity": "150", "unit_rate": "999.99", "line_total": "19500.00"},
            ],
        }
    )
    with pytest.raises(InvoiceExtractionError, match="Ungrounded"):
        LLMInvoiceExtractor(ScriptedProvider(hallucinated)).extract(_doc())


def test_ungrounded_sku_is_rejected() -> None:
    hallucinated = json.dumps(
        {
            "invoice_id": "INV-900", "vendor_name": "Acme",
            "invoice_date": "2026-06-01", "currency": "INR",
            "line_items": [
                {"line_no": 1, "sku": "PHANTOM-X", "description": "x",
                 "quantity": "150", "unit_rate": "130.00", "line_total": "19500.00"},
            ],
        }
    )
    with pytest.raises(InvoiceExtractionError, match="Ungrounded SKU"):
        LLMInvoiceExtractor(ScriptedProvider(hallucinated)).extract(_doc())


def test_real_invoice_error_still_passes_grounding() -> None:
    src = SOURCE_TEXT.replace("19,500.00", "20,000.00")
    j = json.loads(GOOD_JSON)
    j["line_items"][0]["line_total"] = "20000.00"
    invoice = LLMInvoiceExtractor(ScriptedProvider(json.dumps(j))).extract(_doc(src))
    assert invoice.line_items[0].line_total.amount == Decimal("20000.00")


def test_provider_error_is_wrapped() -> None:
    class Failing(LLMProvider):
        def __init__(self) -> None:
            super().__init__(model="fake", max_retries=0, retry_backoff_base=0.0)

        def _raw_complete(self, request: CompletionRequest) -> str:
            raise PermanentLLMError("auth error")

        def close(self) -> None:
            return None

    with pytest.raises(InvoiceExtractionError):
        LLMInvoiceExtractor(Failing()).extract(_doc())


def test_end_to_end_llm_extraction_to_findings() -> None:
    invoice = LLMInvoiceExtractor(ScriptedProvider(GOOD_JSON)).extract(_doc())
    contract = Contract(
        contract_id="C-001", vendor_name="Acme Supplies Pvt Ltd",
        valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31), currency="INR",
        rate_cards=(
            RateCardEntry(
                sku="WIDGET-A", description="Standard widget",
                unit_rate=Money(amount=Decimal("100.00"), currency="INR"),
                volume_discounts=(
                    VolumeDiscountTier(min_quantity=Decimal(100),
                                       discount_pct=Decimal("0.10")),
                ),
            ),
        ),
    )
    service = ReconciliationService(
        matcher=HeuristicMatcher(), rules_engine=RulesEngine(),
        audit_log=InMemoryAuditLog(),
    )
    result = service.reconcile(invoice, [contract])
    assert DiscrepancyType.RATE_MISMATCH in {d.type for d in result.discrepancies}


def test_provider_retries_then_succeeds() -> None:
    class Flaky(LLMProvider):
        def __init__(self) -> None:
            super().__init__(model="fake", max_retries=2, retry_backoff_base=0.0)
            self.calls = 0

        def _raw_complete(self, request: CompletionRequest) -> str:
            self.calls += 1
            if self.calls < 3:
                raise TransientLLMError("temporary")
            return "ok"

        def close(self) -> None:
            return None

    p = Flaky()
    assert p.complete(CompletionRequest(system="s", user="u")) == "ok"
    assert p.calls == 3


def test_provider_permanent_error_not_retried() -> None:
    class Permanent(LLMProvider):
        def __init__(self) -> None:
            super().__init__(model="fake", max_retries=3, retry_backoff_base=0.0)
            self.calls = 0

        def _raw_complete(self, request: CompletionRequest) -> str:
            self.calls += 1
            raise PermanentLLMError("nope")

        def close(self) -> None:
            return None

    p = Permanent()
    with pytest.raises(PermanentLLMError):
        p.complete(CompletionRequest(system="s", user="u"))
    assert p.calls == 1
