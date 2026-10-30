"""Offline extractor that replays hand-written responses.

The demo and the tests have to run without an API key and without spending money, so they
replay ``data/samples/mock_responses/<file>.json``: responses written by hand in the shape the
model returns, including the low confidences you'd expect on faxes and handwriting. They exercise
everything after extraction (matching, flags, CSV, report). They say nothing about how well the
model reads a page; ``make eval`` measures that against the ground truth with the real model.
"""

from __future__ import annotations

import json
from pathlib import Path

from ..models import ExtractedOrder
from ..pages import PreparedDocument
from .base import ExtractionResult


class MockExtractor:
    def __init__(self, responses_dir: str | Path):
        self.responses_dir = Path(responses_dir)

    def extract(self, doc: PreparedDocument, hint: str = "") -> ExtractionResult:
        path = self.responses_dir / f"{Path(doc.filename).stem}.json"
        if not path.exists():
            return ExtractionResult(None, "mock", declined=True, decline_reason=f"no mock response for {doc.filename}")
        payload = json.loads(path.read_text())
        payload.pop("_note", None)
        return ExtractionResult(ExtractedOrder.model_validate(payload), _mode(doc), model="mock")


def _mode(doc: PreparedDocument) -> str:
    """The route the real extractor would take for these pages: text, vision or mixed."""
    kinds = {"text" if p.has_text_layer else "vision" for p in doc.order_pages}
    return "mixed" if len(kinds) > 1 else (kinds.pop() if kinds else "text")
