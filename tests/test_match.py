import pytest

from orderline.match import Settings, list_price, match_customer, match_item, match_ship_to, match_uom, price_differs
from orderline.models import AddressField

S = Settings()


def addr(name, line, city, state, postal):
    return AddressField(name=name, lines=[line], city=city, state=state, postal_code=postal, country="US", confidence=0.95, page=1)


def test_customer_by_domain_and_name(erp):
    m = match_customer(erp, "Northwind Health System", "northwindhealth.example")
    assert (m.customer_id, m.score, m.method) == ("C10021", 100.0, "domain+name")


def test_customer_by_name_alias_without_domain(erp):
    m = match_customer(erp, "Mesa Ortho", "gmail.example")
    assert m.customer_id == "C10132" and m.score >= 90


def test_customer_by_domain_when_the_name_is_unreadable(erp):
    m = match_customer(erp, None, "lakesidesurgical.example")
    assert (m.customer_id, m.method) == ("C10045", "domain")


def test_unknown_customer_scores_low(erp):
    assert match_customer(erp, "Riverbend Urgent Care", "riverbendurgent.example").score < S.customer_check


def test_ship_to_picks_the_right_clinic(erp):
    m = match_ship_to(erp, "C10021", addr("Northwind Health - Eastside Clinic", "455 Lakeview Dr", "Bellevue", "WA", "98004"))
    assert m.ship_to.ship_to_id == "ST-21-02" and m.score >= S.ship_to_accept


def test_ship_to_not_on_file(erp):
    m = match_ship_to(erp, "C10045", addr("Lakeside Surgical - West Annex", "1400 Mineral Point Rd", "Madison", "WI", "53717"))
    assert m.score < S.ship_to_accept


@pytest.mark.parametrize(
    "customer, part, item, method",
    [
        ("C10021", "NW-55102", "MS-GLV-NIT-M", "xref"),
        ("C10021", "nw 55102", "MS-GLV-NIT-M", "xref"),  # spacing and case don't matter
        ("C10117", "4471-L", "MS-GLV-NIT-L", "legacy"),
        ("C10166", "MS-THM-DIG", "MS-THM-DIG", "item_number"),
        ("C10166", "MS THM DIG", "MS-THM-DIG", "normalized"),
        ("C10078", "PVC-GZ-4", "MS-GAU-44S", "fuzzy"),
    ],
)
def test_item_matching_methods(erp, customer, part, item, method):
    m = match_item(erp, customer, part, None, S)
    assert (m.item_number, m.method) == (item, method)


def test_customer_cross_reference_does_not_leak_to_other_customers(erp):
    assert match_item(erp, "C10045", "NW-55102", None, S).method != "xref"


def test_unknown_item_keeps_a_description_hint(erp):
    m = match_item(erp, "C10103", "HP 999-450", "Nitrile exam gloves powder-free medium", S)
    assert m.item_number is None and m.method == "none"
    assert m.candidate == "MS-GLV-NIT-M"


@pytest.mark.parametrize("written, uom", [("case", "CS"), ("BX", "BX"), ("box of 100", "BX"), ("Ea.", "EA")])
def test_uom_aliases(erp, written, uom):
    assert match_uom(erp, "MS-GLV-NIT-M", written).uom == uom


def test_uom_not_valid_for_item(erp):
    assert match_uom(erp, "MS-ALC-PAD", "DZ").uom is None


def test_price_list_falls_back_to_list(erp):
    assert list_price(erp, "CONTRACT-A", "MS-GLV-NIT-M", "BX") == 11.25
    assert list_price(erp, "CONTRACT-A", "MS-THM-DIG", "EA") == 9.95


def test_price_tolerance():
    assert not price_differs(12.50, 12.50, S)
    assert not price_differs(118.00, 118.01, S)
    assert price_differs(12.00, 12.50, S)
