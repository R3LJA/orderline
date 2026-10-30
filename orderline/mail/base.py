from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Iterable, Protocol


@dataclass
class Attachment:
    filename: str
    content_type: str
    data: bytes

    @property
    def is_pdf(self) -> bool:
        return self.content_type == "application/pdf" or self.filename.lower().endswith(".pdf")


@dataclass
class MailMessage:
    id: str
    sender: str
    subject: str
    received_at: datetime | None
    body_text: str
    attachments: list[Attachment] = field(default_factory=list)

    @property
    def sender_domain(self) -> str:
        return self.sender.rsplit("@", 1)[-1].lower().strip(">") if "@" in self.sender else ""

    @property
    def pdfs(self) -> list[Attachment]:
        return [a for a in self.attachments if a.is_pdf]


class MailSource(Protocol):
    """Where orders come from. Implementations: a Microsoft 365 mailbox, or a folder of .eml files."""

    def fetch_new(self) -> Iterable[MailMessage]: ...

    def mark_processed(self, message: MailMessage, outcome: str) -> None: ...
