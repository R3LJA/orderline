"""A folder of .eml files as an inbox. Used by the demo, the tests and on-prem drop folders."""

from __future__ import annotations

import json
from email import policy
from email.parser import BytesParser
from email.utils import parseaddr, parsedate_to_datetime
from pathlib import Path
from typing import Iterator

from .base import Attachment, MailMessage


class FolderMailSource:
    def __init__(self, folder: str | Path, state_file: str | Path | None = None):
        self.folder = Path(folder)
        self.state_file = Path(state_file) if state_file else None
        self._done = self._load_state()

    def fetch_new(self) -> Iterator[MailMessage]:
        for path in sorted(self.folder.glob("*.eml")):
            if path.name in self._done:
                continue
            yield parse_eml(path.read_bytes(), message_id=path.name)

    def mark_processed(self, message: MailMessage, outcome: str) -> None:
        self._done[message.id] = outcome
        if self.state_file:
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            self.state_file.write_text(json.dumps(self._done, indent=2))

    def _load_state(self) -> dict[str, str]:
        if self.state_file and self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {}


def parse_eml(raw: bytes, message_id: str) -> MailMessage:
    msg = BytesParser(policy=policy.default).parsebytes(raw)
    _, sender = parseaddr(str(msg.get("From", "")))
    received = None
    if msg.get("Date"):
        try:
            received = parsedate_to_datetime(str(msg["Date"]))
        except (TypeError, ValueError):
            received = None
    body = msg.get_body(preferencelist=("plain", "html"))
    body_text = body.get_content() if body else ""
    attachments = []
    for part in msg.iter_attachments():
        payload = part.get_payload(decode=True) or b""
        attachments.append(
            Attachment(
                filename=part.get_filename() or "attachment",
                content_type=part.get_content_type(),
                data=payload,
            )
        )
    return MailMessage(
        id=message_id,
        sender=sender.lower(),
        subject=str(msg.get("Subject", "")),
        received_at=received,
        body_text=body_text,
        attachments=attachments,
    )
