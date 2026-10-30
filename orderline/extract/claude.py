"""Extraction with Claude: page text where it is reliable, page images where it is not.

Uses structured outputs through ``messages.parse`` with the ``ExtractedOrder`` pydantic model,
so the response is validated before the pipeline sees it. On the Claude API the request opts in
to server-side refusal fallbacks; Microsoft Foundry deployments are called without them.
"""

from __future__ import annotations

import base64
import os

import anthropic

from ..models import ExtractedOrder
from ..pages import PreparedDocument
from .base import ExtractionResult, Usage
from .prompt import SYSTEM_PROMPT, user_instructions

DEFAULT_MODEL = "claude-opus-5-5"
FALLBACK_BETA = "server-side-fallback-2026-07-01"


def make_client(provider: str | None = None):
    provider = (provider or os.getenv("ORDERLINE_PROVIDER", "anthropic")).lower()
    if provider == "foundry":
        return anthropic.AnthropicFoundry(
            api_key=os.environ["ANTHROPIC_FOUNDRY_API_KEY"],
            resource=os.environ["ANTHROPIC_FOUNDRY_RESOURCE"],
        ), provider
    return anthropic.Anthropic(), "anthropic"


class ClaudeExtractor:
    def __init__(
        self,
        client=None,
        provider: str | None = None,
        model: str | None = None,
        effort: str | None = None,
        max_image_edge: int = 2000,
    ):
        if client is None:
            client, provider = make_client(provider)
        self.client = client
        self.provider = provider or "anthropic"
        self.model = model or os.getenv("ORDERLINE_MODEL", DEFAULT_MODEL)
        self.effort = effort or os.getenv("ORDERLINE_EFFORT", "medium")
        self.max_image_edge = max_image_edge

    def build_content(self, doc: PreparedDocument, hint: str = "") -> tuple[list[dict], str]:
        content: list[dict] = []
        modes = set()
        for page in doc.order_pages:
            if page.has_text_layer:
                modes.add("text")
                content.append(
                    {
                        "type": "text",
                        "text": f"--- Page {page.number} (text layer) ---\n{page.text.strip()}",
                    }
                )
            else:
                modes.add("vision")
                content.append({"type": "text", "text": f"--- Page {page.number} (image) ---"})
                content.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": "image/png",
                            "data": base64.standard_b64encode(page.png_bytes(self.max_image_edge)).decode(),
                        },
                    }
                )
        skipped = [p for p in doc.pages if p not in doc.order_pages]
        if skipped:
            listing = ", ".join(f"page {p.number} ({p.role})" for p in skipped)
            content.append({"type": "text", "text": f"Not sent, detected as non-order pages: {listing}."})
        content.append({"type": "text", "text": user_instructions(hint)})
        mode = "mixed" if len(modes) > 1 else (modes.pop() if modes else "text")
        return content, mode

    def extract(self, doc: PreparedDocument, hint: str = "") -> ExtractionResult:
        content, mode = self.build_content(doc, hint)
        kwargs = dict(
            model=self.model,
            max_tokens=16000,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": content}],
            output_format=ExtractedOrder,
            output_config={"effort": self.effort},
        )
        if self.provider == "anthropic":
            kwargs.update(betas=[FALLBACK_BETA], fallbacks="default")
        response = self.client.beta.messages.parse(**kwargs)

        usage = Usage(
            input_tokens=getattr(response.usage, "input_tokens", 0) or 0,
            output_tokens=getattr(response.usage, "output_tokens", 0) or 0,
            cache_read_input_tokens=getattr(response.usage, "cache_read_input_tokens", 0) or 0,
        )
        if response.stop_reason == "refusal":
            details = getattr(response, "stop_details", None)
            reason = getattr(details, "explanation", None) or getattr(details, "category", None)
            return ExtractionResult(None, mode, usage, self.model, declined=True, decline_reason=str(reason))
        if response.stop_reason == "max_tokens":
            return ExtractionResult(None, mode, usage, self.model, declined=True, decline_reason="output cut off")
        return ExtractionResult(response.parsed_output, mode, usage, self.model)
