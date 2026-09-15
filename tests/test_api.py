"""API route tests (the HTTP boundary).

Exercises both reconcile endpoints through FastAPI's TestClient — the structured
endpoint and the document endpoint — plus the error paths (invalid base64,
unprocessable document). This closes the previously-untested API surface.
"""

from __future__ import annotations

import base64
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("reportlab")

from fastapi.testclient import TestClient  # noqa: E402

from clauseguard.api.app import create_app  # noqa: E402
from clauseguard.domain.models import (  # noqa: E402
    Contract,
    Invoice,
    InvoiceLineItem,
    Money,
    RateCardEntry,
)

client = TestClient(create_app())


def test_healthz() -> None:
    resp = client.get("/health")
    assert resp.status_code == 200


def _structured_payload() -> dict:
    invoice = Invoice(
        invoice_id="INV-900",
        vendor_name="Acme Supplies Pvt Ltd",
        invoice_date=date(2026, 6, 1),
        currency="INR",
        line_items=(
            InvoiceLineItem(
                line_no=1, sku="WIDGET-A", description="Standard widget",
                quantity=Decimal(150),
                unit_rate=Money(amount=Decimal("130.00"), currency="INR"),
                line_total=Money(amount=Decimal("19500.00"), currency="INR"),
            ),
        ),
    )
    contract = Contract(
        contract_id="C-001", vendor_name="Acme Supplies Pvt Ltd",
        valid_from=date(2026, 1, 1), valid_to=date(2026, 12, 31), currency="INR",
        rate_cards=(
            RateCardEntry(
                sku="WIDGET-A", description="Standard widget",
                unit_rate=Money(amount=Decimal("100.00"), currency="INR"),
            ),
        ),
    )
    return {
        "invoice": invoice.model_dump(mode="json"),
        "candidate_contracts": [contract.model_dump(mode="json")],
    }


def test_reconcile_structured_endpoint() -> None:
    resp = client.post("/v1/reconcile", json=_structured_payload())
    assert resp.status_code == 200
    body = resp.json()["result"]
    assert body["contract_id"] == "C-001"
    assert any(d["type"] == "rate_mismatch" for d in body["discrepancies"])


def test_reconcile_document_endpoint() -> None:
    invoice_text = (
        "Invoice-ID: INV-900\nVendor: Acme Supplies Pvt Ltd\nDate: 2026-06-01\n"
        "Currency: INR\n\n"
        "Line | SKU | Description | Qty | Unit-Rate | Line-Total\n"
        "1 | WIDGET-A | Standard widget | 150 | 130.00 | 19500.00\n"
    )
    contract_text = (
        "Contract-ID: C-001\nVendor: Acme Supplies Pvt Ltd\nValid-From: 2026-01-01\n"
        "Valid-To: 2026-12-31\nCurrency: INR\n\n"
        "SKU | Description | Unit-Rate | Volume-Discounts\n"
        "WIDGET-A | Standard widget | 100.00 |\n"
    )
    payload = {
        "invoice_document": {
            "content_base64": base64.b64encode(invoice_text.encode()).decode(),
            "source_ref": "inv.txt",
        },
        "contract_documents": [
            {
                "content_base64": base64.b64encode(contract_text.encode()).decode(),
                "source_ref": "c.txt",
            }
        ],
    }
    resp = client.post("/v1/reconcile-document", json=payload)
    assert resp.status_code == 200
    body = resp.json()["result"]
    assert body["contract_id"] == "C-001"
    assert any(d["type"] == "rate_mismatch" for d in body["discrepancies"])


def test_reconcile_document_rejects_bad_base64() -> None:
    payload = {
        "invoice_document": {"content_base64": "!!!not base64!!!", "source_ref": "x"},
        "contract_documents": [],
    }
    resp = client.post("/v1/reconcile-document", json=payload)
    assert resp.status_code == 400


def test_reconcile_document_unprocessable_when_no_table() -> None:
    junk = base64.b64encode(b"just a letter, nothing to extract").decode()
    payload = {
        "invoice_document": {"content_base64": junk, "source_ref": "x"},
        "contract_documents": [],
    }
    resp = client.post("/v1/reconcile-document", json=payload)
    assert resp.status_code == 422
