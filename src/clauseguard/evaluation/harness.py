"""Evaluation harness: run cases through the real pipeline and score them.

Wires the actual ingestion → extraction → matching → rules pipeline, converts
detected discrepancies and seeded errors into comparable ``(type, line_no)``
keys, and delegates the arithmetic to :mod:`clauseguard.evaluation.metrics`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog
from clauseguard.adapters.extraction.rule_based_contract import (
    RuleBasedContractExtractor,
)
from clauseguard.adapters.extraction.rule_based_invoice import (
    RuleBasedInvoiceExtractor,
)
from clauseguard.adapters.ingestion.pdf_parser import NativePdfParser
from clauseguard.adapters.matching.heuristic import HeuristicMatcher
from clauseguard.evaluation.manifest import EvalCase
from clauseguard.evaluation.metrics import EvalReport, FindingKey, compute_metrics
from clauseguard.logging_config import get_logger
from clauseguard.rules.engine import RulesEngine
from clauseguard.services.reconciliation import ReconciliationService

logger = get_logger(__name__)


@dataclass(frozen=True)
class CaseResult:
    """Per-case detected vs seeded finding keys.

    Attributes:
        case_id: The case identifier.
        detected: Finding keys the engine produced.
        seeded: Finding keys that were planted (ground truth).
    """

    case_id: str
    detected: set[FindingKey]
    seeded: set[FindingKey]

    @property
    def true_positives(self) -> set[FindingKey]:
        return self.detected & self.seeded

    @property
    def false_positives(self) -> set[FindingKey]:
        return self.detected - self.seeded

    @property
    def false_negatives(self) -> set[FindingKey]:
        return self.seeded - self.detected


@dataclass(frozen=True)
class SuiteResult:
    """The full evaluation outcome.

    Attributes:
        report: Aggregated precision/recall/F1.
        cases: Per-case detail (for drill-down and printing).
    """

    report: EvalReport
    cases: list[CaseResult]


class EvaluationHarness:
    """Run :class:`EvalCase` suites through the pipeline and score detection.

    The pipeline components are constructed once and reused across cases.
    """

    def __init__(self) -> None:
        self._parser = NativePdfParser()
        self._invoice_extractor = RuleBasedInvoiceExtractor()
        self._contract_extractor = RuleBasedContractExtractor()
        self._service = ReconciliationService(
            matcher=HeuristicMatcher(),
            rules_engine=RulesEngine(),
            audit_log=InMemoryAuditLog(),
        )

    def run_case(self, case: EvalCase) -> CaseResult:
        """Run a single case and return its detected/seeded finding sets.

        Args:
            case: The labelled case to evaluate.

        Returns:
            The :class:`CaseResult`.

        Raises:
            ExtractionError / IngestionError: Propagated if the case's own text
                is malformed — a broken case should fail loudly, not score 0.
        """
        invoice = self._invoice_extractor.extract(
            self._parser.parse(
                case.invoice_text.encode("utf-8"),
                source_ref=f"{case.case_id}/invoice",
            )
        )
        contract = self._contract_extractor.extract(
            self._parser.parse(
                case.contract_text.encode("utf-8"),
                source_ref=f"{case.case_id}/contract",
            )
        )
        result = self._service.reconcile(invoice, [contract])

        detected: set[FindingKey] = {
            (d.type.value, d.invoice_line_no) for d in result.discrepancies
        }
        seeded: set[FindingKey] = {
            (e.type.value, e.line_no) for e in case.seeded_errors
        }
        logger.info(
            "Case evaluated",
            extra={
                "case_id": case.case_id,
                "detected": len(detected),
                "seeded": len(seeded),
            },
        )
        return CaseResult(case_id=case.case_id, detected=detected, seeded=seeded)

    def run_suite(self, cases: Sequence[EvalCase]) -> SuiteResult:
        """Run every case and aggregate the metrics.

        Args:
            cases: The cases to evaluate.

        Returns:
            A :class:`SuiteResult` with the aggregate report and per-case detail.
        """
        case_results = [self.run_case(c) for c in cases]
        report = compute_metrics(
            ((cr.detected, cr.seeded) for cr in case_results),
            total_cases=len(case_results),
        )
        return SuiteResult(report=report, cases=case_results)