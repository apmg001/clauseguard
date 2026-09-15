"""Tests for the document reconciliation use-case (ingestion+extraction+reconcile).

Feeds *raw document bytes* — a real reportlab-generated PDF invoice and a
text contract — through the whole chain and asserts findings come out, proving
the extraction pipeline is connected end to end (not just reachable from tests).
"""

from __future__ import annotations

import io

import pytest

pytest.importorskip("reportlab")

from reportlab.lib import colors  # noqa: E402
from reportlab.lib.pagesizes import A4  # noqa: E402
from reportlab.lib.styles import getSampleStyleSheet  # noqa: E402
from reportlab.platypus import (  # noqa: E402
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from clauseguard.adapters.audit.in_memory import InMemoryAuditLog  # noqa: E402
from clauseguard.adapters.extraction.cascading import (  # noqa: E402
    CascadingInvoiceExtractor,
)
from clauseguard.adapters.extraction.layout_aware_invoice import (  # noqa: E402
    LayoutAwareInvoiceExtractor,
)
from clauseguard.adapters.extraction.rule_based_contract import (  # noqa: E402
    RuleBasedContractExtractor,
)
from clauseguard.adapters.extraction.rule_based_invoice import (  # noqa: E402
    RuleBasedInvoiceExtractor,
)
from clauseguard.adapters.ingestion.pdf_parser import NativePdfParser  # noqa: E402
from clauseguard.adapters.matching.heuristic import HeuristicMatcher  # noqa: E402
from clauseguard.domain.enums import DiscrepancyType  # noqa: E402
from clauseguard.rules.engine import RulesEngine  # noqa: E402
from clauseguard.services.document_reconciliation import (  # noqa: E402
    DocumentPayload,
    DocumentReconciliationService,
)
from clauseguard.services.reconciliation import ReconciliationService  # noqa: E402

CONTRACT_TEXT = """\
Contract-ID: C-001
Vendor: Acme Supplies Pvt Ltd
Valid-From: 2026-01-01
Valid-To: 2026-12-31
Currency: INR

SKU | Description | Unit-Rate | Volume-Discounts
WIDGET-A | Standard widget | 100.00 | 100:0.10
"""


def _invoice_pdf_bytes() -> bytes:
    buf = io.BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4)
    styles = getSampleStyleSheet()
    table = Table(
        [
            ["#", "Item Code", "Description", "Qty", "Unit Price", "Amount"],
            ["1", "WIDGET-A", "Standard widget", "150", "Rs 130.00", "Rs 19,500.00"],
        ]
    )
    table.setStyle(
        TableStyle(
            [
                ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
                ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
            ]
        )
    )
    doc.build(
        [
            Paragraph("ACME SUPPLIES PVT LTD", styles["Title"]),
            Paragraph("Invoice No: INV-900 &nbsp; Date: 01/06/2026", styles["Normal"]),
            Spacer(1, 12),
            table,
        ]
    )
    return buf.getvalue()


def _service() -> DocumentReconciliationService:
    return DocumentReconciliationService(
        parser=NativePdfParser(),
        invoice_extractor=CascadingInvoiceExtractor(
            [LayoutAwareInvoiceExtractor(), RuleBasedInvoiceExtractor()]
        ),
        contract_extractor=RuleBasedContractExtractor(),
        reconciliation_service=ReconciliationService(
            matcher=HeuristicMatcher(),
            rules_engine=RulesEngine(),
            audit_log=InMemoryAuditLog(),
        ),
    )


def test_reconciles_real_pdf_invoice_against_text_contract() -> None:
    result = _service().reconcile_documents(
        DocumentPayload(content=_invoice_pdf_bytes(), source_ref="inv.pdf"),
        [DocumentPayload(content=CONTRACT_TEXT.encode("utf-8"), source_ref="c.txt")],
    )
    assert result.contract_id == "C-001"
    detected = {d.type for d in result.discrepancies}
    assert DiscrepancyType.RATE_MISMATCH in detected
    assert result.audit_id is not None


def test_cascade_falls_back_to_text_tier_for_text_invoice() -> None:
    invoice_text = """\
Invoice-ID: INV-901
Vendor: Acme Supplies Pvt Ltd
Date: 2026-06-01
Currency: INR

Line | SKU | Description | Qty | Unit-Rate | Line-Total
1 | WIDGET-A | Standard widget | 150 | 130.00 | 19500.00
"""
    result = _service().reconcile_documents(
        DocumentPayload(content=invoice_text.encode("utf-8"), source_ref="inv.txt"),
        [DocumentPayload(content=CONTRACT_TEXT.encode("utf-8"), source_ref="c.txt")],
    )
    assert {d.type for d in result.discrepancies} & {DiscrepancyType.RATE_MISMATCH}
