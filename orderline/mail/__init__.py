from .base import Attachment, MailMessage, MailSource
from .classify import Classification, classify_message
from .folder import FolderMailSource, parse_eml
from .graph import GraphMailSource

__all__ = [
    "Attachment",
    "Classification",
    "FolderMailSource",
    "GraphMailSource",
    "MailMessage",
    "MailSource",
    "classify_message",
    "parse_eml",
]
