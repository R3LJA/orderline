from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest

from orderline.erp import ErpData
from orderline.extract.base import ExtractionResult
from orderline.mail.base import Attachment, MailMessage
from orderline.models import ExtractedOrder
from orderline.pages import prepare_pdf

ROOT = Path(__file__).resolve().parent.parent
SAMPLES = ROOT / "data" / "samples"


@pytest.fixture(scope="session")
def erp() -> ErpData:
    return ErpData.load(ROOT / "data" / "erp")


@pytest.fixture(scope="session")
def mock_payloads() -> dict[str, dict]:
    out = {}
    for path in (SAMPLES / "mock_responses").glob("*.json"):
        payload = json.loads(path.read_text())
        payload.pop("_note", None)
        out[path.stem] = payload
    return out


@pytest.fixture
def order_payload(mock_payloads):
    """A deep copy of a sample extraction, to edit per test."""

    def make(sample_id: str = "01-northwind-4500884512") -> dict:
        return copy.deepcopy(mock_payloads[sample_id])

    return make


@pytest.fixture(scope="session")
def sample_pdf():
    def load(sample_id: str) -> bytes:
        return (SAMPLES / "pdf" / f"{sample_id}.pdf").read_bytes()

    return load


@pytest.fixture(scope="session")
def northwind_doc(sample_pdf):
    return prepare_pdf(sample_pdf("01-northwind-4500884512"), "01-northwind-4500884512.pdf")


def message(sender: str = "purchasing@northwindhealth.example", subject: str = "PO 1", body: str = "", pdfs=(b"%PDF",)) -> MailMessage:
    return MailMessage(
        id="m1",
        sender=sender,
        subject=subject,
        received_at=None,
        body_text=body,
        attachments=[Attachment(f"po-{i}.pdf", "application/pdf", data) for i, data in enumerate(pdfs)],
    )


def result(payload: dict) -> ExtractionResult:
    return ExtractionResult(ExtractedOrder.model_validate(payload), "mock", model="mock")
