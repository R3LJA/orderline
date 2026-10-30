from types import SimpleNamespace

import pytest

from orderline.extract.claude import FALLBACK_BETA, ClaudeExtractor
from orderline.extract.mock import MockExtractor
from orderline.models import ExtractedOrder
from orderline.pages import PreparedDocument, prepare_pdf

from .conftest import SAMPLES


class FakeMessages:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return self.response


def fake_client(response):
    messages = FakeMessages(response)
    return SimpleNamespace(beta=SimpleNamespace(messages=messages)), messages


def response(parsed=None, stop_reason="end_turn", stop_details=None):
    usage = SimpleNamespace(input_tokens=5200, output_tokens=900, cache_read_input_tokens=0)
    return SimpleNamespace(parsed_output=parsed, stop_reason=stop_reason, stop_details=stop_details, usage=usage)


def test_text_pages_go_as_text_and_skipped_pages_are_named(sample_pdf):
    doc = prepare_pdf(sample_pdf("03-pinevalley-77812"), "03.pdf")
    client, _ = fake_client(response())
    content, mode = ClaudeExtractor(client=client, provider="anthropic").build_content(doc)
    assert mode == "text"
    assert not any(block["type"] == "image" for block in content)
    assert "Page 2 (text layer)" in content[0]["text"]
    assert any("page 1 (cover)" in b.get("text", "") and "page 4 (terms)" in b.get("text", "") for b in content)


def test_scans_go_as_images(sample_pdf):
    doc = prepare_pdf(sample_pdf("06-mesa-fax-MOP-1187"), "06.pdf")
    client, _ = fake_client(response())
    content, mode = ClaudeExtractor(client=client, provider="anthropic").build_content(doc)
    image = next(b for b in content if b["type"] == "image")
    assert mode == "vision"
    assert image["source"]["media_type"] == "image/png" and len(image["source"]["data"]) > 1000


def test_request_uses_structured_output_and_fallbacks(northwind_doc, mock_payloads):
    parsed = ExtractedOrder.model_validate(mock_payloads["01-northwind-4500884512"])
    client, messages = fake_client(response(parsed))
    out = ClaudeExtractor(client=client, provider="anthropic", model="claude-opus-5-5", effort="medium").extract(northwind_doc)
    call = messages.calls[0]
    assert call["output_format"] is ExtractedOrder
    assert call["model"] == "claude-opus-5-5" and call["output_config"] == {"effort": "medium"}
    assert call["betas"] == [FALLBACK_BETA] and call["fallbacks"] == "default"
    assert out.order.po_number.value == "4500884512"
    assert (out.usage.input_tokens, out.usage.output_tokens) == (5200, 900)


def test_foundry_requests_have_no_fallback_beta(northwind_doc, mock_payloads):
    parsed = ExtractedOrder.model_validate(mock_payloads["01-northwind-4500884512"])
    client, messages = fake_client(response(parsed))
    ClaudeExtractor(client=client, provider="foundry").extract(northwind_doc)
    assert "fallbacks" not in messages.calls[0] and "betas" not in messages.calls[0]


@pytest.mark.parametrize("stop_reason", ["refusal", "max_tokens"])
def test_refusal_and_cutoff_are_reported_not_raised(northwind_doc, stop_reason):
    client, _ = fake_client(response(None, stop_reason, SimpleNamespace(category="other", explanation=None)))
    out = ClaudeExtractor(client=client, provider="anthropic").extract(northwind_doc)
    assert out.declined and out.order is None


def test_mock_extractor_replays_and_reports_missing(northwind_doc):
    extractor = MockExtractor(SAMPLES / "mock_responses")
    found = PreparedDocument("01-northwind-4500884512.pdf", northwind_doc.pages)
    assert extractor.extract(found).order.po_number.value == "4500884512"
    missing = extractor.extract(PreparedDocument("nope.pdf", northwind_doc.pages))
    assert missing.declined and "no mock response" in missing.decline_reason


def test_wire_schema_forbids_extra_keys(mock_payloads):
    payload = dict(mock_payloads["01-northwind-4500884512"])
    payload["surprise"] = 1
    with pytest.raises(Exception):
        ExtractedOrder.model_validate(payload)
