import pytest

from orderline.extract.base import ExtractionResult
from orderline.models import FlagCode, Severity
from orderline.pages import PreparedDocument
from orderline.prepare import SeenOrders, prepare_order

from .conftest import message, result


def run(erp, northwind_doc, payload, sender="purchasing@northwindhealth.example", seen=None, doc=None):
    return prepare_order(erp, message(sender=sender), doc or northwind_doc, result(payload), seen or SeenOrders())


def codes(order):
    return {f.code for f in order.flags}


def test_clean_order_has_no_flags(erp, northwind_doc, order_payload):
    order = run(erp, northwind_doc, order_payload())
    assert order.flags == []
    assert order.customer_id == "C10021" and order.ship_to.ship_to_id == "ST-21-02"
    assert [l.item_number for l in order.lines] == ["MS-GLV-NIT-M", "MS-SYR-10L", "MS-MSK-L3", "MS-CTH-F16"]
    assert order.status == "waiting_for_review"  # never released


def test_missing_po_number_is_a_blocker(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["po_number"]["value"] = None
    flag = next(f for f in run(erp, northwind_doc, payload).flags if f.code == FlagCode.missing_po_number)
    assert flag.severity == Severity.blocker


def test_low_confidence_field_asks_for_a_check(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["lines"][1]["quantity"]["confidence"] = 0.55
    flag = next(f for f in run(erp, northwind_doc, payload).flags if f.code == FlagCode.unclear_field)
    assert (flag.severity, flag.line_number, flag.field) == (Severity.check, 2, "quantity")
    assert "55% sure" in flag.message


def test_unknown_customer(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["customer_name"]["value"] = "Riverbend Urgent Care"
    order = run(erp, northwind_doc, payload, sender="purchasing@riverbendurgent.example")
    assert FlagCode.unknown_customer in codes(order) and order.customer_id is None


def test_uncertain_customer_is_matched_but_flagged(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["customer_name"]["value"] = "Northwind Hlth Sys"
    order = run(erp, northwind_doc, payload, sender="someone@gmail.example")
    assert order.customer_id == "C10021"
    assert FlagCode.customer_uncertain in codes(order)


def test_unknown_ship_to(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["ship_to"].update(name="Northwind Health - New Tower", lines=["900 Pine St"], city="Tacoma", postal_code="98402")
    assert FlagCode.unknown_ship_to in codes(run(erp, northwind_doc, payload))


def test_unknown_item_and_fuzzy_item(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["lines"][0]["customer_part"]["value"] = "ZZ-00000"
    payload["lines"][1]["customer_part"]["value"] = "NW-6120"  # dropped a digit
    order = run(erp, northwind_doc, payload)
    assert FlagCode.unknown_item in codes(order)
    fuzzy = next(f for f in order.flags if f.code == FlagCode.item_fuzzy_match)
    assert fuzzy.expected == "MS-SYR-10L"


def test_uom_mismatch(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["lines"][0]["unit_of_measure"]["value"] = "DZ"
    flag = next(f for f in run(erp, northwind_doc, payload).flags if f.code == FlagCode.uom_mismatch)
    assert flag.severity == Severity.blocker and "BX" in flag.expected


def test_price_mismatch_shows_both_prices(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["lines"][0]["unit_price"]["value"] = 12.50  # list price, but Northwind has a contract
    flag = next(f for f in run(erp, northwind_doc, payload).flags if f.code == FlagCode.price_mismatch)
    assert (flag.found, flag.expected) == ("12.50", "11.25")


def test_no_price_on_file(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["lines"][0]["unit_of_measure"]["value"] = "EA"  # gloves by the each: valid unit, no price
    assert FlagCode.no_price_on_file in codes(run(erp, northwind_doc, payload))


def test_duplicate_po_is_flagged_on_the_second_copy(erp, northwind_doc, order_payload, tmp_path):
    seen = SeenOrders(tmp_path / "seen.json")
    first = run(erp, northwind_doc, order_payload(), seen=seen)
    assert FlagCode.possible_duplicate not in codes(first)
    second = run(erp, northwind_doc, order_payload(), seen=SeenOrders(tmp_path / "seen.json"))
    flag = next(f for f in second.flags if f.code == FlagCode.possible_duplicate)
    assert flag.expected == first.order_key


def test_unreadable_date(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["requested_date"]["value"] = "asap pls"
    assert FlagCode.date_unclear in codes(run(erp, northwind_doc, payload))


def test_not_a_purchase_order_returns_none(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["is_purchase_order"] = False
    assert run(erp, northwind_doc, payload) is None


def test_model_declined_becomes_a_blocker(erp, northwind_doc):
    declined = ExtractionResult(None, "vision", declined=True, decline_reason="refusal")
    order = prepare_order(erp, message(), northwind_doc, declined, SeenOrders())
    assert codes(order) == {FlagCode.model_declined} and order.blockers


def test_no_lines(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["lines"] = []
    assert FlagCode.no_lines in codes(run(erp, northwind_doc, payload))


def test_orientation_uncertain_is_reported(erp, northwind_doc, order_payload):
    doc = PreparedDocument(filename="x.pdf", pages=list(northwind_doc.pages))
    page = doc.pages[0]
    original = (page.rotation_source, page.rotation_confidence)
    page.rotation_source, page.rotation_confidence = "pixels", 0.5
    try:
        order = run(erp, northwind_doc, order_payload(), doc=doc)
    finally:
        page.rotation_source, page.rotation_confidence = original
    flag = next(f for f in order.flags if f.code == FlagCode.orientation_uncertain)
    assert flag.severity == Severity.info and flag.page == 1


def test_blockers_sort_first(erp, northwind_doc, order_payload):
    payload = order_payload()
    payload["po_number"]["value"] = None
    payload["lines"][0]["unit_price"]["value"] = 99.0
    order = run(erp, northwind_doc, payload)
    assert order.flags[0].severity == Severity.blocker
