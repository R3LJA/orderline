"""A Microsoft 365 order mailbox through Microsoft Graph (v1.0), app-only.

Endpoints and permissions follow the Graph v1.0 reference:

* ``GET /users/{mailbox}/mailFolders/{folder}/messages`` lists messages (pages through
  ``@odata.nextLink``; the ``Prefer: outlook.body-content-type="text"`` header returns
  plain-text bodies).
* ``GET /users/{mailbox}/messages/{id}/attachments`` returns ``fileAttachment`` objects
  with base64 ``contentBytes``.
* ``PATCH /users/{mailbox}/messages/{id}`` marks a message read and tags it.

Application permission: ``Mail.ReadWrite`` (reading alone needs ``Mail.Read``; marking a
message read needs write). Scope the app to the one order mailbox with Exchange Online
RBAC for applications so it cannot read anyone else's mail.
"""

from __future__ import annotations

import base64
from datetime import datetime
from typing import Iterator

import httpx

from .base import Attachment, MailMessage

GRAPH = "https://graph.microsoft.com/v1.0"
LOGIN = "https://login.microsoftonline.com/{tenant}/oauth2/v2.0/token"
CATEGORY = "Orderline"


class GraphMailSource:
    def __init__(
        self,
        tenant_id: str,
        client_id: str,
        client_secret: str,
        mailbox: str,
        folder: str = "Inbox",
        page_size: int = 25,
        http: httpx.Client | None = None,
    ):
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.mailbox = mailbox
        self.folder = folder
        self.page_size = page_size
        self.http = http or httpx.Client(timeout=30)
        self._token: str | None = None

    # -- auth

    def _auth(self) -> dict[str, str]:
        if not self._token:
            response = self.http.post(
                LOGIN.format(tenant=self.tenant_id),
                data={
                    "client_id": self.client_id,
                    "client_secret": self.client_secret,
                    "scope": "https://graph.microsoft.com/.default",
                    "grant_type": "client_credentials",
                },
            )
            response.raise_for_status()
            self._token = response.json()["access_token"]
        return {"Authorization": f"Bearer {self._token}"}

    # -- MailSource

    def fetch_new(self) -> Iterator[MailMessage]:
        url: str | None = f"{GRAPH}/users/{self.mailbox}/mailFolders/{self.folder}/messages"
        params: dict[str, str] | None = {
            "$filter": "isRead eq false and hasAttachments eq true",
            "$select": "id,subject,from,receivedDateTime,body,hasAttachments",
            "$top": str(self.page_size),
        }
        headers = {**self._auth(), "Prefer": 'outlook.body-content-type="text"'}
        while url:
            response = self.http.get(url, params=params, headers=headers)
            response.raise_for_status()
            payload = response.json()
            for item in payload.get("value", []):
                yield self._message(item)
            url, params = payload.get("@odata.nextLink"), None  # the link already carries the query

    def mark_processed(self, message: MailMessage, outcome: str) -> None:
        response = self.http.patch(
            f"{GRAPH}/users/{self.mailbox}/messages/{message.id}",
            headers=self._auth(),
            json={"isRead": True, "categories": [CATEGORY, f"{CATEGORY}: {outcome}"]},
        )
        response.raise_for_status()

    # -- helpers

    def _message(self, item: dict) -> MailMessage:
        sender = ((item.get("from") or {}).get("emailAddress") or {}).get("address", "")
        received = item.get("receivedDateTime")
        return MailMessage(
            id=item["id"],
            sender=sender.lower(),
            subject=item.get("subject") or "",
            received_at=datetime.fromisoformat(received.replace("Z", "+00:00")) if received else None,
            body_text=(item.get("body") or {}).get("content", ""),
            attachments=list(self._attachments(item["id"])) if item.get("hasAttachments") else [],
        )

    def _attachments(self, message_id: str) -> Iterator[Attachment]:
        response = self.http.get(
            f"{GRAPH}/users/{self.mailbox}/messages/{message_id}/attachments", headers=self._auth()
        )
        response.raise_for_status()
        for att in response.json().get("value", []):
            if att.get("@odata.type", "").endswith("fileAttachment") and att.get("contentBytes"):
                yield Attachment(
                    filename=att.get("name") or "attachment",
                    content_type=att.get("contentType") or "application/octet-stream",
                    data=base64.b64decode(att["contentBytes"]),
                )
