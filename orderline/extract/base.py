from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol

from ..models import ExtractedOrder
from ..pages import PreparedDocument


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_input_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_input_tokens += other.cache_read_input_tokens


@dataclass
class ExtractionResult:
    order: ExtractedOrder | None
    mode: str  # text | vision | mixed | mock
    usage: Usage = field(default_factory=Usage)
    model: str | None = None
    declined: bool = False
    decline_reason: str | None = None


class Extractor(Protocol):
    def extract(self, doc: PreparedDocument, hint: str = "") -> ExtractionResult: ...
