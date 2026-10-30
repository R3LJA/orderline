"""Decide which emails carry purchase orders.

Order inboxes also receive invoices, quotes, remittances, statements, newsletters and
replies. This is a cheap, explainable first pass: an email needs a PDF and more order
signals than non-order signals. Anything it lets through is checked again by the model,
which returns ``is_purchase_order=false`` for documents that are not orders.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .base import MailMessage

ORDER_SIGNALS = [
    (r"\bpurchase\s+order\b", "purchase order"),
    (r"\bp\.?\s?o\.?\s*(#|no\.?|number|\d)", "a PO number"),
    (r"\bnew\s+order\b", "new order"),
    (r"\border\s+(attached|enclosed)\b", "order attached"),
    (r"\bplease\s+(process|ship|fill)\b", "please process"),
]
NOT_ORDER_SIGNALS = [
    (r"\binvoice\b", "invoice"),
    (r"\bremittance\b", "remittance"),
    (r"\bstatement\s+of\s+account\b", "statement of account"),
    (r"\b(request\s+for\s+)?quot(e|ation)\b", "quote"),
    (r"\bnewsletter\b", "newsletter"),
    (r"\bunsubscribe\b", "unsubscribe"),
    (r"\bpayment\s+(advice|confirmation)\b", "payment advice"),
]
ORDER_FILENAME = re.compile(r"(^|[^a-z])(po|p\.o|purchase[ _-]?order|order)([^a-z]|$)", re.I)
NOT_ORDER_FILENAME = re.compile(r"(invoice|inv[_-]?\d|quote|statement|remit)", re.I)


@dataclass
class Classification:
    is_order: bool
    score: int
    reasons: list[str]


def classify_message(message: MailMessage) -> Classification:
    if not message.pdfs:
        return Classification(False, -10, ["no PDF attached"])

    text = f"{message.subject}\n{message.body_text}".lower()
    score, reasons = 0, []
    for pattern, label in ORDER_SIGNALS:
        if re.search(pattern, text):
            score += 2
            reasons.append(f'says "{label}"')
    for pattern, label in NOT_ORDER_SIGNALS:
        if re.search(pattern, text):
            score -= 3
            reasons.append(f'says "{label}"')
    for pdf in message.pdfs:
        if ORDER_FILENAME.search(pdf.filename):
            score += 2
            reasons.append(f"{pdf.filename} is named like an order")
        if NOT_ORDER_FILENAME.search(pdf.filename):
            score -= 3
            reasons.append(f"{pdf.filename} is named like an invoice, quote or statement")

    # A bare PDF with no wording either way still goes to the model: losing an order is worse
    # than one extra call that comes back is_purchase_order=false.
    return Classification(score >= 0, score, reasons or ["PDF attached, no wording either way"])
