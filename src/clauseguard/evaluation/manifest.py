"""Evaluation case + seeded-error manifest models.

An :class:`EvalCase` is a self-contained, labelled test: the raw text of an
invoice and its governing contract, plus the discrepancies deliberately planted
in them. The manifest is the ground truth the harness scores against.
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from clauseguard.domain.enums import DiscrepancyType


class SeededError(BaseModel):
    """One deliberately-planted discrepancy (ground truth).

    Attributes:
        type: The expected discrepancy category (enum-validated, so a typo in a
            case fails fast).
        line_no: The 1-based invoice line it sits on, or None for a
            document-level error (e.g. out-of-term dating).
        note: Human-readable description of what was planted.
    """

    model_config = ConfigDict(frozen=True)

    type: DiscrepancyType
    line_no: int | None = None
    note: str = ""


class EvalCase(BaseModel):
    """A labelled reconciliation case for evaluation.

    Attributes:
        case_id: Stable identifier.
        description: Short human summary of what the case exercises.
        invoice_text: Raw invoice text (fed through the real extractor).
        contract_text: Raw contract text (fed through the real extractor).
        seeded_errors: The planted discrepancies to recover (may be empty, which
            asserts the engine raises no false positives on a clean case).
    """

    model_config = ConfigDict(frozen=True)

    case_id: str
    description: str = ""
    invoice_text: str
    contract_text: str
    seeded_errors: tuple[SeededError, ...] = Field(default_factory=tuple)