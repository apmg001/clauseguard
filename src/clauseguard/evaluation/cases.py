"""Built-in synthetic evaluation cases.

Each case pairs invoice + contract text with the discrepancies planted in it.
Together they exercise all six implemented rule types, plus a clean case that
must produce *no* findings (a false-positive check). Synthetic and controlled on
purpose: they validate the engine and the harness end to end, and serve as the
template for adding harder or real-world cases later.
"""

from __future__ import annotations

from clauseguard.domain.enums import DiscrepancyType
from clauseguard.evaluation.manifest import EvalCase, SeededError

# --- Case A: overbilling (rate + missed discount + uncontracted item) ------ #
_CASE_OVERBILLING = EvalCase(
    case_id="overbilling",
    description="Rate mismatch, missed volume discount, and an uncontracted item.",
    invoice_text="""\
Invoice-ID: INV-900
Vendor: Acme Supplies Pvt Ltd
Date: 2026-06-01
Currency: INR

Line | SKU | Description | Qty | Unit-Rate | Line-Total
1 | WIDGET-A | Standard widget | 150 | 130.00 | 19500.00
2 | GADGET-Z | Mystery gadget | 5 | 50.00 | 250.00
""",
    contract_text="""\
Contract-ID: C-001
Vendor: Acme Supplies Pvt Ltd
Valid-From: 2026-01-01
Valid-To: 2026-12-31
Currency: INR

SKU | Description | Unit-Rate | Volume-Discounts
WIDGET-A | Standard widget | 100.00 | 100:0.10
""",
    seeded_errors=(
        SeededError(type=DiscrepancyType.RATE_MISMATCH, line_no=1),
        SeededError(type=DiscrepancyType.MISSED_VOLUME_DISCOUNT, line_no=1),
        SeededError(type=DiscrepancyType.UNCONTRACTED_ITEM, line_no=2),
    ),
)

# --- Case B: arithmetic error + out-of-term dating ------------------------- #
_CASE_ARITHMETIC_TERM = EvalCase(
    case_id="arithmetic_and_term",
    description="Line total inconsistent with qty x rate; invoice outside term.",
    invoice_text="""\
Invoice-ID: INV-901
Vendor: Beta Traders
Date: 2025-06-01
Currency: INR

Line | SKU | Description | Qty | Unit-Rate | Line-Total
1 | BOLT-1 | Steel bolt | 2 | 100.00 | 250.00
""",
    contract_text="""\
Contract-ID: C-002
Vendor: Beta Traders
Valid-From: 2026-01-01
Valid-To: 2026-12-31
Currency: INR

SKU | Description | Unit-Rate | Volume-Discounts
BOLT-1 | Steel bolt | 100.00 |
""",
    seeded_errors=(
        SeededError(type=DiscrepancyType.ARITHMETIC_ERROR, line_no=1),
        SeededError(type=DiscrepancyType.OUT_OF_TERM, line_no=None),
    ),
)

# --- Case C: currency mismatch --------------------------------------------- #
_CASE_CURRENCY = EvalCase(
    case_id="currency_mismatch",
    description="Invoice billed in USD against an INR contract.",
    invoice_text="""\
Invoice-ID: INV-902
Vendor: Gamma Corp
Date: 2026-03-01
Currency: USD

Line | SKU | Description | Qty | Unit-Rate | Line-Total
1 | PART-X | Component X | 1 | 100.00 | 100.00
""",
    contract_text="""\
Contract-ID: C-003
Vendor: Gamma Corp
Valid-From: 2026-01-01
Valid-To: 2026-12-31
Currency: INR

SKU | Description | Unit-Rate | Volume-Discounts
PART-X | Component X | 100.00 |
""",
    seeded_errors=(
        SeededError(type=DiscrepancyType.CURRENCY_MISMATCH, line_no=1),
    ),
)

# --- Case D: clean invoice (no errors -> false-positive check) ------------- #
_CASE_CLEAN = EvalCase(
    case_id="clean",
    description="Fully compliant invoice; the engine must find nothing.",
    invoice_text="""\
Invoice-ID: INV-903
Vendor: Delta Ltd
Date: 2026-05-01
Currency: INR

Line | SKU | Description | Qty | Unit-Rate | Line-Total
1 | NUT-9 | Hex nut | 10 | 20.00 | 200.00
""",
    contract_text="""\
Contract-ID: C-004
Vendor: Delta Ltd
Valid-From: 2026-01-01
Valid-To: 2026-12-31
Currency: INR

SKU | Description | Unit-Rate | Volume-Discounts
NUT-9 | Hex nut | 20.00 | 100:0.10
""",
    seeded_errors=(),
)

BUILTIN_CASES: tuple[EvalCase, ...] = (
    _CASE_OVERBILLING,
    _CASE_ARITHMETIC_TERM,
    _CASE_CURRENCY,
    _CASE_CLEAN,
)