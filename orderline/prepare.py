"""Turn one extraction into a prepared order: matched to ERP data, with every doubt flagged.

The rules here are deterministic on purpose. The model reads the page; code decides whether a
price is off, a part is unknown or a PO was already received, so the same input always gives
the same flags and a rep can trust what each flag means.
"""

from __future__ import annotations

import hashlib
import json
from datetime import date

from .erp import ErpData
from .extract.base import ExtractionResult
from .mail.base import MailMessage
from .match import (
    Settings,
    list_price,
    match_customer,
    match_item,
    match_ship_to,
    match_uom,
    price_differs,
)
from .models import (
    ExtractedOrder,
    Flag,
    FlagCode,
    MatchedLine,
    MatchedShipTo,
    PreparedOrder,
    Severity,
)
from .pages import PreparedDocument


def prepare_order(
    erp: ErpData,
    message: MailMessage,
    doc: PreparedDocument,
    result: ExtractionResult,
    seen: "SeenOrders",
    settings: Settings | None = None,
) -> PreparedOrder | None:
    """Returns None when the document is not a purchase order."""
    settings = settings or Settings()
    flags: list[Flag] = []

    for page in doc.uncertain_orientation:
        flags.append(Flag(code=FlagCode.orientation_uncertain, severity=Severity.info, page=page,
                          message=f"Page {page}: could not tell which way is up; the model read it as is."))

    order = result.order
    if result.declined or order is None:
        flags.append(Flag(code=FlagCode.model_declined, severity=Severity.blocker,
                          message=f"No extraction: {result.decline_reason or 'the model returned nothing'}. Key this order by hand."))
        return _empty(message, doc, result, flags)
    if not order.is_purchase_order:
        return None

    _confidence_flags(order, settings, flags)

    customer = match_customer(erp, order.customer_name.value, message.sender_domain)
    if customer.score < settings.customer_check:
        flags.append(Flag(code=FlagCode.unknown_customer, severity=Severity.blocker, field="customer",
                          found=order.customer_name.value or message.sender,
                          message="No customer in the ERP matches this name or sender."))
        customer_id = None
    else:
        customer_id = customer.customer_id
        if customer.score < settings.customer_accept:
            flags.append(Flag(code=FlagCode.customer_uncertain, severity=Severity.check, field="customer",
                              found=order.customer_name.value, expected=customer.name,
                              message=f"Matched to {customer.name} with score {customer.score:.0f}; confirm."))

    ship = match_ship_to(erp, customer_id, order.ship_to)
    written_ship = ", ".join(p for p in [order.ship_to.name, *order.ship_to.lines, order.ship_to.city,
                                         order.ship_to.state, order.ship_to.postal_code] if p)
    if customer_id and (not ship.ship_to or ship.score < settings.ship_to_accept):
        flags.append(Flag(code=FlagCode.unknown_ship_to, severity=Severity.blocker, field="ship_to",
                          found=written_ship or None, page=order.ship_to.page,
                          message="Ship-to address is not on file for this customer. Add it or pick the right one."))

    po_number = (order.po_number.value or "").strip() or None
    if not po_number:
        flags.append(Flag(code=FlagCode.missing_po_number, severity=Severity.blocker, field="po_number",
                          message="No PO number on the document. Call the customer or use their reference."))

    price_list_id = erp.customers[customer_id].price_list if customer_id else "LIST"
    lines: list[MatchedLine] = []
    for index, line in enumerate(order.lines, start=1):
        number = line.line_number or index
        item = match_item(erp, customer_id, line.customer_part.value, line.description.value, settings)
        if item.method == "none":
            hint = f" Closest item: {item.candidate}." if item.candidate else ""
            flags.append(Flag(code=FlagCode.unknown_item, severity=Severity.blocker, line_number=number,
                              field="customer_part", found=line.customer_part.value, page=line.customer_part.page,
                              message=f"Line {number}: part {line.customer_part.value!r} is not in the item master or cross-references.{hint}"))
        elif item.method == "fuzzy":
            flags.append(Flag(code=FlagCode.item_fuzzy_match, severity=Severity.check, line_number=number,
                              field="customer_part", found=line.customer_part.value, expected=item.item_number,
                              message=f"Line {number}: {line.customer_part.value!r} looks like {item.item_number} (score {item.score:.0f}); confirm."))

        uom = match_uom(erp, item.item_number, line.unit_of_measure.value)
        if item.item_number and not uom.uom:
            allowed = ", ".join(r.uom for r in erp.uoms.get(item.item_number, [])) or "none on file"
            flags.append(Flag(code=FlagCode.uom_mismatch, severity=Severity.blocker, line_number=number,
                              field="unit_of_measure", found=line.unit_of_measure.value, expected=allowed,
                              message=f"Line {number}: unit {line.unit_of_measure.value!r} is not valid for {item.item_number} (valid: {allowed})."))

        expected = list_price(erp, price_list_id, item.item_number, uom.uom)
        written_price = line.unit_price.value
        if item.item_number and uom.uom and expected is None:
            flags.append(Flag(code=FlagCode.no_price_on_file, severity=Severity.check, line_number=number,
                              message=f"Line {number}: no price on file for {item.item_number} per {uom.uom}."))
        elif expected is not None and written_price is not None and price_differs(written_price, expected, settings):
            flags.append(Flag(code=FlagCode.price_mismatch, severity=Severity.check, line_number=number,
                              field="unit_price", found=f"{written_price:.2f}", expected=f"{expected:.2f}",
                              page=line.unit_price.page,
                              message=f"Line {number}: PO says {written_price:.2f} per {uom.uom}, price list says {expected:.2f}."))

        lines.append(MatchedLine(
            line_number=number,
            customer_part=line.customer_part.value,
            description=line.description.value,
            quantity=line.quantity.value,
            unit_of_measure=uom.uom,
            unit_of_measure_as_written=line.unit_of_measure.value,
            unit_price=written_price,
            item_number=item.item_number,
            match_method=item.method,
            match_score=round(item.score, 1),
            list_price=expected,
            page=line.customer_part.page or line.quantity.page,
        ))

    if not lines:
        flags.append(Flag(code=FlagCode.no_lines, severity=Severity.blocker,
                          message="No line items found on the order pages."))

    requested = _parse_date(order.requested_date.value)
    if order.requested_date.value and requested is None:
        flags.append(Flag(code=FlagCode.date_unclear, severity=Severity.check, field="requested_date",
                          found=order.requested_date.value, message="Requested date could not be read as a date."))

    content_hash = _content_hash(customer_id, po_number, lines)
    order_key = content_hash[:10]
    duplicate_of = seen.check(customer_id, po_number, content_hash, order_key)
    if duplicate_of:
        flags.append(Flag(code=FlagCode.possible_duplicate, severity=Severity.blocker, field="po_number",
                          found=po_number, expected=duplicate_of,
                          message=f"Looks like a PO already received ({duplicate_of}). Check before importing twice."))

    return PreparedOrder(
        order_key=order_key,
        source_message_id=message.id,
        source_file=doc.filename,
        sender=message.sender,
        customer_id=customer_id,
        customer_name=customer.name if customer_id else order.customer_name.value,
        customer_score=round(customer.score, 1),
        po_number=po_number,
        order_date=_parse_date(order.order_date.value),
        requested_date=requested,
        ship_to=MatchedShipTo(
            ship_to_id=ship.ship_to.ship_to_id if ship.ship_to and ship.score >= settings.ship_to_accept else None,
            score=round(ship.score, 1),
            as_written=written_ship,
        ),
        shipping_instructions=order.shipping_instructions.value,
        carrier=order.carrier.value,
        carrier_account=order.carrier_account.value,
        lines=lines,
        flags=_sorted(flags),
        extraction_mode=result.mode,
        page_count=len(doc.pages),
        order_pages=[p.number for p in doc.order_pages],
        content_hash=content_hash,
    )


def _confidence_flags(order: ExtractedOrder, settings: Settings, flags: list[Flag]) -> None:
    header = {
        "po_number": order.po_number,
        "customer_name": order.customer_name,
        "requested_date": order.requested_date,
        "carrier_account": order.carrier_account,
    }
    for name, field in header.items():
        if field.value is not None and field.confidence < settings.confidence_threshold:
            flags.append(Flag(code=FlagCode.unclear_field, severity=Severity.check, field=name, page=field.page,
                              found=str(field.value),
                              message=f"{name.replace('_', ' ').capitalize()} is hard to read ({field.confidence:.0%} sure), read as {field.value!r}."))
    for address_name, address in (("ship_to", order.ship_to),):
        if address.confidence < settings.confidence_threshold and any([address.name, *address.lines]):
            flags.append(Flag(code=FlagCode.unclear_field, severity=Severity.check, field=address_name, page=address.page,
                              message=f"Ship-to address is hard to read ({address.confidence:.0%} sure)."))
    for index, line in enumerate(order.lines, start=1):
        number = line.line_number or index
        for name, field in (("customer_part", line.customer_part), ("quantity", line.quantity),
                            ("unit_of_measure", line.unit_of_measure), ("unit_price", line.unit_price)):
            if field.value is not None and field.confidence < settings.confidence_threshold:
                shown = f"{field.value:g}" if isinstance(field.value, float) else repr(field.value)
                flags.append(Flag(code=FlagCode.unclear_field, severity=Severity.check, field=name,
                                  line_number=number, page=field.page, found=str(field.value),
                                  message=f"Line {number}: {name.replace('_', ' ')} is hard to read ({field.confidence:.0%} sure), read as {shown}."))


class SeenOrders:
    """Remembers prepared POs so a PO sent twice (resend, fax plus email) is flagged, not imported twice."""

    def __init__(self, path=None):
        from pathlib import Path

        self.path = Path(path) if path else None
        self.by_po: dict[str, str] = {}
        self.by_hash: dict[str, str] = {}
        if self.path and self.path.exists():
            data = json.loads(self.path.read_text())
            self.by_po, self.by_hash = data.get("by_po", {}), data.get("by_hash", {})

    def check(self, customer_id: str | None, po_number: str | None, content_hash: str, order_key: str) -> str | None:
        po_key = f"{customer_id}:{(po_number or '').upper()}" if po_number else None
        previous = (self.by_po.get(po_key) if po_key else None) or self.by_hash.get(content_hash)
        if po_key and po_key not in self.by_po:
            self.by_po[po_key] = order_key
        self.by_hash.setdefault(content_hash, order_key)
        self._save()
        return previous

    def _save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps({"by_po": self.by_po, "by_hash": self.by_hash}, indent=2))


def _content_hash(customer_id, po_number, lines: list[MatchedLine]) -> str:
    basis = {
        "customer": customer_id,
        "po": (po_number or "").upper(),
        "lines": [(l.item_number or l.customer_part, l.quantity, l.unit_of_measure) for l in lines],
    }
    return hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    from datetime import datetime

    text = value.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%m-%d-%Y", "%b %d, %Y", "%B %d, %Y", "%d %b %Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def _sorted(flags: list[Flag]) -> list[Flag]:
    rank = {Severity.blocker: 0, Severity.check: 1, Severity.info: 2}
    return sorted(flags, key=lambda f: (rank[f.severity], f.line_number or 0))


def _empty(message: MailMessage, doc: PreparedDocument, result: ExtractionResult, flags: list[Flag]) -> PreparedOrder:
    key = hashlib.sha256(f"{message.id}:{doc.filename}".encode()).hexdigest()
    return PreparedOrder(
        order_key=key[:10], source_message_id=message.id, source_file=doc.filename, sender=message.sender,
        customer_id=None, customer_name=None, customer_score=0.0, po_number=None, order_date=None,
        requested_date=None, ship_to=MatchedShipTo(ship_to_id=None, score=0.0, as_written=""),
        shipping_instructions=None, carrier=None, carrier_account=None, lines=[], flags=_sorted(flags),
        extraction_mode=result.mode, page_count=len(doc.pages), order_pages=[p.number for p in doc.order_pages],
        content_hash=key,
    )
