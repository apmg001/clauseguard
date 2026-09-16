"""Tests for the invoice-extractor cascade wiring at the composition root.

Verifies the LLM tier is appended only when enabled — no model/network needed,
since we only inspect how many tiers the cascade was built with.
"""

from __future__ import annotations

from clauseguard.adapters.extraction.cascading import CascadingInvoiceExtractor
from clauseguard.api.dependencies import build_invoice_extractor
from clauseguard.config import Settings


def test_llm_tier_absent_by_default() -> None:
    extractor = build_invoice_extractor(Settings(enable_llm_extraction=False))
    assert isinstance(extractor, CascadingInvoiceExtractor)
    assert len(extractor._extractors) == 2  # noqa: SLF001 - white-box wiring check


def test_llm_tier_appended_when_enabled() -> None:
    extractor = build_invoice_extractor(Settings(enable_llm_extraction=True))
    assert len(extractor._extractors) == 3  # noqa: SLF001
    assert type(extractor._extractors[-1]).__name__ == "LLMInvoiceExtractor"
