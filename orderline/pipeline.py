"""Inbox to prepared orders: classify, prepare pages, extract, match, flag, write.

Orderline prepares orders. It never releases one: every CSV carries a review status, and the
existing ERP import and the customer service team decide what goes through.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass, field
from pathlib import Path

from .erp import ErpData
from .extract.base import Extractor, Usage
from .mail.base import MailMessage, MailSource
from .mail.classify import classify_message
from .match import Settings
from .models import PreparedOrder
from .output import CsvSpec, write_order
from .pages import prepare_pdf
from .prepare import SeenOrders, prepare_order


@dataclass
class SkippedItem:
    message_id: str
    subject: str
    reason: str


@dataclass
class ProcessedOrder:
    order: PreparedOrder
    csv_path: Path
    sidecar_path: Path
    thumbnail_png_b64: str
    subject: str


@dataclass
class BatchResult:
    orders: list[ProcessedOrder] = field(default_factory=list)
    skipped: list[SkippedItem] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)


def run_batch(
    source: MailSource,
    erp: ErpData,
    extractor: Extractor,
    spec: CsvSpec,
    out_dir: str | Path,
    seen: SeenOrders,
    settings: Settings | None = None,
) -> BatchResult:
    batch = BatchResult()
    for message in source.fetch_new():
        outcome = _process_message(message, erp, extractor, spec, Path(out_dir), seen, settings, batch)
        source.mark_processed(message, outcome)
    return batch


def _process_message(message: MailMessage, erp, extractor, spec, out_dir, seen, settings, batch: BatchResult) -> str:
    verdict = classify_message(message)
    if not verdict.is_order:
        batch.skipped.append(SkippedItem(message.id, message.subject, "; ".join(verdict.reasons[:2])))
        return "not an order"

    prepared_any = False
    for attachment in message.pdfs:
        doc = prepare_pdf(attachment.data, attachment.filename)
        result = extractor.extract(doc, hint=f"From {message.sender}. Subject: {message.subject}")
        batch.usage.add(result.usage)
        order = prepare_order(erp, message, doc, result, seen, settings)
        if order is None:
            batch.skipped.append(SkippedItem(message.id, message.subject, f"{attachment.filename}: model says not a purchase order"))
            continue
        csv_path, sidecar = write_order(order, spec, out_dir)
        first = doc.order_pages[0] if doc.order_pages else doc.pages[0]
        thumb = base64.b64encode(first.png_bytes(max_long_edge=900)).decode()
        batch.orders.append(ProcessedOrder(order, csv_path, sidecar, thumb, message.subject))
        prepared_any = True
    return "prepared" if prepared_any else "not an order"
