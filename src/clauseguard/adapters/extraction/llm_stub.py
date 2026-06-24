"""Adapter: LLM extractor stub (Phase 1 placeholder).

Phase 4 replaces this with a self-hosted, schema-constrained LLM extractor for
semantically messy clauses. Keeping a stub behind the port lets the rest of the
pipeline be built and tested now. It raises to make accidental reliance obvious.
"""

from __future__ import annotations

from clauseguard.exceptions import ContractExtractionError
from clauseguard.ports.ingestion import ParsedDocument


class LlmContractExtractorStub:
    """Placeholder contract extractor; not implemented until Phase 4."""

    def extract(self, document: ParsedDocument):  # type: ignore[no-untyped-def]
        """Raise to signal the LLM path is not wired yet.

        Raises:
            ContractExtractionError: Always, in Phase 1.
        """
        raise ContractExtractionError(
            "LLM extraction is a Phase 4 capability; use a rule-based "
            "extractor or provide structured input in Phase 1."
        )
