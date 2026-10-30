"""Generate the synthetic sample set: ERP reference data, order emails with PDFs, ground truth
and the replayed mock responses used by the offline demo.

Everything here is invented: companies, people, addresses, part numbers and prices. No real
customer document was used. Run from the repo root:

    python scripts/make_samples.py

The PDFs cover the cases an order desk actually sees: clean system PDFs in different layouts,
a fax with a cover sheet and a terms page, a sideways scan, an upside-down scan, a noisy fax,
a handwritten form without a PO number, an unknown customer and a resent duplicate.
"""

from __future__ import annotations

import csv
import io
import json
import random
from email.message import EmailMessage
from email.utils import format_datetime
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import pymupdf
from PIL import Image, ImageFilter
from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import letter
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen import canvas

ROOT = Path(__file__).resolve().parent.parent
ERP = ROOT / "data" / "erp"
SAMPLES = ROOT / "data" / "samples"
VENDOR = "Alder Medical Products, Inc."
VENDOR_ADDR = ["1800 Industrial Pkwy", "Minneapolis, MN 55413"]
VENDOR_EMAIL = "orders@aldermedical.example"
random.seed(7)
np.random.seed(7)

HAND = "Helvetica-Oblique"
for candidate in ("/System/Library/Fonts/Supplemental/Bradley Hand Bold.ttf",):
    if Path(candidate).exists():
        pdfmetrics.registerFont(TTFont("Hand", candidate))
        HAND = "Hand"

# --------------------------------------------------------------------------- ERP reference data

CUSTOMERS = [
    ("C10021", "Northwind Health System", "Northwind Health|NWHS", "northwindhealth.example", "CONTRACT-A"),
    ("C10045", "Lakeside Surgical Center", "Lakeside Surgical|LSC", "lakesidesurgical.example", "LIST"),
    ("C10078", "Pine Valley Clinics", "Pine Valley Clinic Group|PVC", "pinevalleyclinics.example", "CONTRACT-B"),
    ("C10103", "Harbor Point Medical Supply", "Harbor Point|HPMS", "harborpointmed.example", "DIST"),
    ("C10117", "St. Brigid Rehabilitation Center", "St Brigid Rehab|Saint Brigid Rehab", "stbrigidrehab.example", "LIST"),
    ("C10132", "Mesa Orthopedic Partners", "Mesa Ortho", "mesaortho.example", "CONTRACT-A"),
    ("C10150", "Cedar Ridge Dental Group", "Cedar Ridge Dental", "cedarridgedental.example", "LIST"),
    ("C10166", "Bayview Animal Hospital", "Bayview Vet", "bayviewanimal.example", "LIST"),
]

SHIP_TOS = [
    ("ST-21-01", "C10021", "Northwind Health - Main Hospital", "1200 Harbor Blvd", "Receiving Dock 3", "Seattle", "WA", "98101", "US"),
    ("ST-21-02", "C10021", "Northwind Health - Eastside Clinic", "455 Lakeview Dr", "Suite 200", "Bellevue", "WA", "98004", "US"),
    ("ST-45-01", "C10045", "Lakeside Surgical Center", "88 Shoreline Ave", "", "Madison", "WI", "53703", "US"),
    ("ST-78-01", "C10078", "Pine Valley Clinics - Central Supply", "2100 Ridge Rd", "Bldg C", "Boise", "ID", "83702", "US"),
    ("ST-78-02", "C10078", "Pine Valley Clinics - Meridian", "77 Fairview Ave", "", "Meridian", "ID", "83642", "US"),
    ("ST-03-01", "C10103", "Harbor Point Medical Supply DC", "9 Dockside Way", "", "Portland", "ME", "04101", "US"),
    ("ST-17-01", "C10117", "St. Brigid Rehabilitation Center", "310 Elm St", "", "Dayton", "OH", "45402", "US"),
    ("ST-32-01", "C10132", "Mesa Orthopedic Partners", "5150 E Camelback Rd", "Suite 310", "Phoenix", "AZ", "85018", "US"),
    ("ST-50-01", "C10150", "Cedar Ridge Dental Group", "640 Cedar Ridge Pkwy", "", "Asheville", "NC", "28803", "US"),
    ("ST-66-01", "C10166", "Bayview Animal Hospital", "21 Bay St", "", "Monterey", "CA", "93940", "US"),
]

ITEMS = [
    ("MS-GLV-NIT-M", "Nitrile exam gloves, powder-free, medium", "EA"),
    ("MS-GLV-NIT-L", "Nitrile exam gloves, powder-free, large", "EA"),
    ("MS-SYR-10L", "Syringe 10 mL Luer lock, sterile", "EA"),
    ("MS-GAU-44S", "Gauze sponge 4x4 12-ply, sterile", "EA"),
    ("MS-TAP-1SC", "Silicone surgical tape 1 in", "RL"),
    ("MS-MSK-L3", "Procedure mask ASTM level 3", "EA"),
    ("MS-ALC-PAD", "Alcohol prep pad, medium", "EA"),
    ("MS-BND-EL4", "Elastic bandage 4 in", "EA"),
    ("MS-CTH-F16", "Foley catheter 16 Fr, 2-way", "EA"),
    ("MS-SHP-1QT", "Sharps container 1 qt", "EA"),
    ("MS-THM-DIG", "Digital oral thermometer", "EA"),
    ("MS-IVK-STD", "IV start kit, standard", "EA"),
    ("MS-SPL-WR", "Wrist splint, universal", "EA"),
    ("MS-DRS-FOAM", "Foam dressing 4x4, bordered", "EA"),
]

UOMS = [
    ("MS-GLV-NIT-M", "EA", 1, "each|ea|glove"), ("MS-GLV-NIT-M", "BX", 100, "box|bx|bx/100|box of 100"),
    ("MS-GLV-NIT-M", "CS", 1000, "case|cs|cse|ca|case/10bx"),
    ("MS-GLV-NIT-L", "EA", 1, "each|ea|glove"), ("MS-GLV-NIT-L", "BX", 100, "box|bx|bx/100|box of 100"),
    ("MS-GLV-NIT-L", "CS", 1000, "case|cs|cse|ca|case/10bx"),
    ("MS-SYR-10L", "EA", 1, "each|ea"), ("MS-SYR-10L", "BX", 100, "box|bx"), ("MS-SYR-10L", "CS", 800, "case|cs"),
    ("MS-GAU-44S", "EA", 1, "each|ea"), ("MS-GAU-44S", "PK", 10, "pack|pk|pkg|pkt"), ("MS-GAU-44S", "CS", 1200, "case|cs"),
    ("MS-TAP-1SC", "RL", 1, "roll|rl|rls|ea|each"), ("MS-TAP-1SC", "BX", 12, "box|bx"),
    ("MS-MSK-L3", "EA", 1, "each|ea"), ("MS-MSK-L3", "BX", 50, "box|bx|bx/50"), ("MS-MSK-L3", "CS", 500, "case|cs"),
    ("MS-ALC-PAD", "EA", 1, "each|ea"), ("MS-ALC-PAD", "BX", 200, "box|bx"), ("MS-ALC-PAD", "CS", 4000, "case|cs"),
    ("MS-BND-EL4", "EA", 1, "each|ea"), ("MS-BND-EL4", "BX", 10, "box|bx"),
    ("MS-CTH-F16", "EA", 1, "each|ea"), ("MS-CTH-F16", "BX", 10, "box|bx|bx/10"),
    ("MS-SHP-1QT", "EA", 1, "each|ea"), ("MS-SHP-1QT", "CS", 24, "case|cs"),
    ("MS-THM-DIG", "EA", 1, "each|ea"), ("MS-THM-DIG", "BX", 12, "box|bx"),
    ("MS-IVK-STD", "EA", 1, "each|ea|kit"), ("MS-IVK-STD", "CS", 50, "case|cs"),
    ("MS-SPL-WR", "EA", 1, "each|ea"),
    ("MS-DRS-FOAM", "EA", 1, "each|ea"), ("MS-DRS-FOAM", "BX", 10, "box|bx"),
]

PRICES = {
    "LIST": {
        ("MS-GLV-NIT-M", "BX"): 12.50, ("MS-GLV-NIT-M", "CS"): 118.00, ("MS-GLV-NIT-L", "BX"): 12.50,
        ("MS-GLV-NIT-L", "CS"): 118.00, ("MS-SYR-10L", "BX"): 24.00, ("MS-SYR-10L", "CS"): 180.00,
        ("MS-GAU-44S", "PK"): 3.20, ("MS-GAU-44S", "CS"): 352.00, ("MS-TAP-1SC", "RL"): 4.10,
        ("MS-TAP-1SC", "BX"): 45.00, ("MS-MSK-L3", "BX"): 18.00, ("MS-MSK-L3", "CS"): 165.00,
        ("MS-ALC-PAD", "BX"): 4.50, ("MS-ALC-PAD", "CS"): 82.00, ("MS-BND-EL4", "EA"): 2.40,
        ("MS-BND-EL4", "BX"): 22.00, ("MS-CTH-F16", "EA"): 6.80, ("MS-CTH-F16", "BX"): 64.00,
        ("MS-SHP-1QT", "EA"): 5.25, ("MS-SHP-1QT", "CS"): 118.00, ("MS-THM-DIG", "EA"): 9.95,
        ("MS-THM-DIG", "BX"): 110.00, ("MS-IVK-STD", "EA"): 4.60, ("MS-IVK-STD", "CS"): 210.00,
        ("MS-SPL-WR", "EA"): 14.50, ("MS-DRS-FOAM", "EA"): 4.10, ("MS-DRS-FOAM", "BX"): 38.00,
    },
    "CONTRACT-A": {
        ("MS-GLV-NIT-M", "BX"): 11.25, ("MS-GLV-NIT-M", "CS"): 106.00, ("MS-GLV-NIT-L", "BX"): 11.25,
        ("MS-SYR-10L", "BX"): 21.60, ("MS-MSK-L3", "BX"): 16.20, ("MS-DRS-FOAM", "BX"): 34.20,
        ("MS-CTH-F16", "BX"): 57.60, ("MS-SPL-WR", "EA"): 13.05,
    },
    "CONTRACT-B": {
        ("MS-GLV-NIT-M", "BX"): 11.80, ("MS-GAU-44S", "PK"): 2.95, ("MS-IVK-STD", "CS"): 195.00,
        ("MS-TAP-1SC", "RL"): 3.85,
    },
    "DIST": {
        ("MS-GLV-NIT-M", "CS"): 98.00, ("MS-GLV-NIT-L", "CS"): 98.00, ("MS-SYR-10L", "CS"): 158.00,
        ("MS-ALC-PAD", "CS"): 71.00, ("MS-SHP-1QT", "CS"): 104.00,
    },
}

XREF = [
    ("C10021", "NW-55102", "MS-GLV-NIT-M", "customer"), ("C10021", "NW-55103", "MS-GLV-NIT-L", "customer"),
    ("C10021", "NW-61200", "MS-SYR-10L", "customer"), ("C10021", "NW-70450", "MS-MSK-L3", "customer"),
    ("C10021", "NW-80016", "MS-CTH-F16", "customer"),
    ("C10078", "PVC-GL-M", "MS-GLV-NIT-M", "customer"), ("C10078", "PVC-GZ-44", "MS-GAU-44S", "customer"),
    ("C10078", "PVC-IVK", "MS-IVK-STD", "customer"), ("C10078", "PVC-TP1", "MS-TAP-1SC", "customer"),
    ("C10103", "HP 300-118", "MS-GLV-NIT-M", "customer"), ("C10103", "HP 300-119", "MS-GLV-NIT-L", "customer"),
    ("C10103", "HP 300-210", "MS-SYR-10L", "customer"), ("C10103", "HP 410-022", "MS-ALC-PAD", "customer"),
    ("C10103", "HP 520-001", "MS-SHP-1QT", "customer"),
    ("C10132", "MOP-SPL-01", "MS-SPL-WR", "customer"), ("C10132", "MOP-FD-44", "MS-DRS-FOAM", "customer"),
    ("*", "4471-M", "MS-GLV-NIT-M", "legacy"), ("*", "4471-L", "MS-GLV-NIT-L", "legacy"),
    ("*", "2290-10", "MS-SYR-10L", "legacy"), ("*", "8812", "MS-CTH-F16", "legacy"), ("*", "7730", "MS-BND-EL4", "legacy"),
]


def write_erp() -> None:
    ERP.mkdir(parents=True, exist_ok=True)
    _csv(ERP / "customers.csv", ["customer_id", "name", "aliases", "email_domains", "price_list"], CUSTOMERS)
    _csv(ERP / "ship_to.csv", ["ship_to_id", "customer_id", "name", "line1", "line2", "city", "state", "postal_code", "country"], SHIP_TOS)
    _csv(ERP / "items.csv", ["item_number", "description", "base_uom", "active"], [(*i, "Y") for i in ITEMS])
    _csv(ERP / "uom.csv", ["item_number", "uom", "factor", "aliases"], UOMS)
    _csv(ERP / "item_xref.csv", ["customer_id", "customer_part", "item_number", "kind"], XREF)
    rows = [(pl, item, uom, f"{price:.2f}") for pl, table in PRICES.items() for (item, uom), price in table.items()]
    _csv(ERP / "prices.csv", ["price_list", "item_number", "uom", "unit_price"], rows)


def _csv(path: Path, header: list[str], rows) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.writer(handle)
        writer.writerow(header)
        writer.writerows(rows)


# --------------------------------------------------------------------------- the orders

# Each order: what the document says (truth), how it is rendered, and what the mock model returns.
ORDERS = [
    dict(
        id="01-northwind-4500884512", layout="corporate", render="clean",
        sender="purchasing@northwindhealth.example", subject="PO 4500884512 - Alder Medical",
        body="Hello, please see attached purchase order 4500884512. Ship to our Eastside Clinic.\n\nThanks,\nDana Whitfield\nSupply Chain, Northwind Health",
        customer="Northwind Health System", po="4500884512", order_date="2026-10-27", requested="2026-11-12",
        bill_to=("Northwind Health System", ["Accounts Payable", "PO Box 88120"], "Seattle", "WA", "98111"),
        ship_to=("Northwind Health - Eastside Clinic", ["455 Lakeview Dr", "Suite 200"], "Bellevue", "WA", "98004"),
        ship_via="UPS Ground", carrier_account="UPS acct 4X7Y92 (bill third party)", instructions="Deliver Mon-Fri 7am-3pm. Call 425-555-0142 on arrival.",
        lines=[("NW-55102", "Nitrile exam gloves PF medium", 20, "BX", 11.25), ("NW-61200", "Syringe 10mL luer lock", 10, "BX", 21.60),
               ("NW-70450", "Procedure mask level 3", 5, "BX", 16.20), ("NW-80016", "Foley cath 16Fr", 2, "BX", 57.60)],
        expect=dict(customer_id="C10021", ship_to_id="ST-21-02", status="clean", flags=[]),
    ),
    dict(
        id="02-lakeside-LSC-2291", layout="orderform", render="clean",
        sender="mreyes@lakesidesurgical.example", subject="New order LSC-2291",
        body="Order attached. Please process.\nMarco Reyes, Materials Mgmt",
        customer="Lakeside Surgical Center", po="LSC-2291", order_date="2026-10-28", requested="2026-11-05",
        bill_to=("Lakeside Surgical Center", ["88 Shoreline Ave"], "Madison", "WI", "53703"),
        ship_to=("Lakeside Surgical Center", ["88 Shoreline Ave"], "Madison", "WI", "53703"),
        ship_via="Best way", carrier_account=None, instructions=None,
        lines=[("MS-GLV-NIT-L", "Nitrile gloves large", 15, "BX", 12.00), ("MS-GAU-44S", "Gauze 4x4 sterile", 1, "case", 352.00),
               ("MS-ALC-PAD", "Alcohol prep pads", 10, "BX", 4.50)],
        expect=dict(customer_id="C10045", ship_to_id="ST-45-01", status="check", flags=["price_mismatch"]),
    ),
    dict(
        id="03-pinevalley-77812", layout="pinevalley", render="clean",
        sender="supply@pinevalleyclinics.example", subject="PO# 77812 (4 pages incl. cover)",
        body="Faxed copy attached for PO 77812.",
        customer="Pine Valley Clinics", po="77812", order_date="2026-10-26", requested="2026-11-09",
        bill_to=("Pine Valley Clinics", ["Accounts Payable", "2100 Ridge Rd"], "Boise", "ID", "83702"),
        ship_to=("Pine Valley Clinics - Central Supply", ["2100 Ridge Rd", "Bldg C"], "Boise", "ID", "83702"),
        ship_via="FedEx Ground", carrier_account="FedEx 2231-9984-1", instructions="Ship complete only.",
        lines=[("PVC-GL-M", "Gloves nitrile M", 40, "BX", 11.80), ("PVC-GZ-44", "Gauze 4x4", 24, "PKG", 2.95),
               ("PVC-IVK", "IV start kit", 2, "CS", 195.00), ("PVC-TP1", "Silicone tape 1in", 36, "RL", 3.85),
               ("PVC-GL-M", "Gloves nitrile M (Meridian clinic stock)", 10, "BX", 11.80)],
        expect=dict(customer_id="C10078", ship_to_id="ST-78-01", status="clean", flags=[]),
    ),
    dict(
        id="04-harborpoint-HP33019", layout="corporate", render="clean",
        sender="buyer@harborpointmed.example", subject="Purchase Order HP33019",
        body="Please confirm receipt of PO HP33019.\n\nHarbor Point Medical Supply - Purchasing",
        customer="Harbor Point Medical Supply", po="HP33019", order_date="2026-10-28", requested="2026-11-15",
        bill_to=("Harbor Point Medical Supply", ["9 Dockside Way"], "Portland", "ME", "04101"),
        ship_to=("Harbor Point Medical Supply DC", ["9 Dockside Way"], "Portland", "ME", "04101"),
        ship_via="LTL - our carrier", carrier_account="Estes acct 0098812", instructions="Pallets max 60 in high.",
        lines=[("4471-M", "Gloves nitrile medium (legacy #)", 12, "CS", 98.00), ("HP 300-210", "Syringe 10cc LL", 6, "CS", 158.00),
               ("HP 410-022", "Alcohol prep pad", 8, "CS", 71.00), ("HP 999-450", "Exam table paper 18in", 20, "CS", 41.00)],
        expect=dict(customer_id="C10103", ship_to_id="ST-03-01", status="blocked", flags=["unknown_item"]),
    ),
    dict(
        id="05-stbrigid-handwritten", layout="handwritten", render="scan",
        sender="frontdesk@stbrigidrehab.example", subject="supply order",
        body="Hi, our order form is attached. We don't have a PO number yet, sorry. -Ann",
        customer="St. Brigid Rehabilitation Center", po=None, order_date="2026-10-29", requested="2026-11-06",
        bill_to=("St. Brigid Rehabilitation Center", ["310 Elm St"], "Dayton", "OH", "45402"),
        ship_to=("St. Brigid Rehabilitation Center", ["310 Elm St"], "Dayton", "OH", "45402"),
        ship_via=None, carrier_account=None, instructions="Leave at side door if closed",
        lines=[("4471-L", "gloves large", 3, "case", 118.00), ("7730", "ace bandage 4 inch", 2, "box", 22.00),
               ("MS-SPL-WR", "wrist splints", 6, "ea", 14.50)],
        mock_conf={("lines", 1, "quantity"): 0.58},
        expect=dict(customer_id="C10117", ship_to_id="ST-17-01", status="blocked", flags=["missing_po_number", "unclear_field"]),
    ),
    dict(
        id="06-mesa-fax-MOP-1187", layout="corporate", render="fax",
        sender="ops@mesaortho.example", subject="PO MOP-1187",
        body="Fax copy of PO MOP-1187 attached. Need by 11/10.",
        customer="Mesa Orthopedic Partners", po="MOP-1187", order_date="2026-10-28", requested="2026-11-10",
        bill_to=("Mesa Orthopedic Partners", ["5150 E Camelback Rd", "Suite 310"], "Phoenix", "AZ", "85018"),
        ship_to=("Mesa Orthopedic Partners", ["5150 E Camelback Rd", "Suite 310"], "Phoenix", "AZ", "85018"),
        ship_via="FedEx 2Day", carrier_account="FedEx 7714-2290-3", instructions=None,
        lines=[("MOP-SPL-01", "Wrist splint universal", 12, "EA", 13.05), ("MOP-FD-44", "Foam dressing 4x4 bordered", 6, "BX", 34.20),
               ("MS-GLV-NIT-M", "Gloves nitrile M", 1, "CS", 106.00)],
        mock_conf={("lines", 2, "unit_price"): 0.62},
        expect=dict(customer_id="C10132", ship_to_id="ST-32-01", status="check", flags=["unclear_field"]),
    ),
    dict(
        id="07-cedarridge-sideways-CRD-0419", layout="orderform", render="scan", rotate=90,
        sender="office@cedarridgedental.example", subject="Order CRD-0419",
        body="Scanned PO attached, sorry it's sideways!",
        customer="Cedar Ridge Dental Group", po="CRD-0419", order_date="2026-10-27", requested="2026-11-03",
        bill_to=("Cedar Ridge Dental Group", ["640 Cedar Ridge Pkwy"], "Asheville", "NC", "28803"),
        ship_to=("Cedar Ridge Dental Group", ["640 Cedar Ridge Pkwy"], "Asheville", "NC", "28803"),
        ship_via="UPS Ground", carrier_account=None, instructions=None,
        lines=[("MS-GLV-NIT-M", "Nitrile gloves medium", 8, "BX", 12.50), ("MS-MSK-L3", "Level 3 masks", 6, "BX", 18.00),
               ("MS-SHP-1QT", "Sharps container 1qt", 4, "EA", 5.25)],
        expect=dict(customer_id="C10150", ship_to_id="ST-50-01", status="clean", flags=[]),
    ),
    dict(
        id="08-bayview-upsidedown-BV-311", layout="corporate", render="scan", rotate=180,
        sender="manager@bayviewanimal.example", subject="PO BV-2026-311",
        body="PO attached.",
        customer="Bayview Animal Hospital", po="BV-2026-311", order_date="2026-10-29", requested="2026-11-07",
        bill_to=("Bayview Animal Hospital", ["21 Bay St"], "Monterey", "CA", "93940"),
        ship_to=("Bayview Animal Hospital", ["21 Bay St"], "Monterey", "CA", "93940"),
        ship_via="UPS Ground", carrier_account=None, instructions=None,
        lines=[("MS-THM-DIG", "Digital thermometers", 1, "BX", 110.00), ("MS-BND-EL4", "Elastic bandage 4in", 3, "BX", 22.00),
               ("MS-ALC-PAD", "Alcohol prep pads", 2, "DZ", 4.50)],
        expect=dict(customer_id="C10166", ship_to_id="ST-66-01", status="blocked", flags=["uom_mismatch"]),
    ),
    dict(
        id="09-riverbend-unknown-RUC-5520", layout="corporate", render="clean",
        sender="purchasing@riverbendurgent.example", subject="Purchase order RUC-5520",
        body="First order with you, please set us up. PO attached.",
        customer="Riverbend Urgent Care", po="RUC-5520", order_date="2026-10-29", requested="2026-11-14",
        bill_to=("Riverbend Urgent Care", ["4 Mill Race Rd"], "Eugene", "OR", "97401"),
        ship_to=("Riverbend Urgent Care", ["4 Mill Race Rd"], "Eugene", "OR", "97401"),
        ship_via="UPS Ground", carrier_account=None, instructions=None,
        lines=[("MS-GLV-NIT-M", "Gloves nitrile M", 10, "BX", 12.50), ("MS-IVK-STD", "IV start kit", 1, "CS", 210.00)],
        expect=dict(customer_id=None, ship_to_id=None, status="blocked", flags=["unknown_customer"]),
    ),
    dict(
        id="10-northwind-4500884512-resend", same_as="01-northwind-4500884512", layout="corporate", render="clean",
        sender="purchasing@northwindhealth.example", subject="RESEND: PO 4500884512 - Alder Medical",
        body="Resending in case the first one didn't come through.\nDana",
        expect=dict(customer_id="C10021", ship_to_id="ST-21-02", status="blocked", flags=["possible_duplicate"]),
    ),
    dict(
        id="11-pinevalley-77840", layout="corporate", render="clean",
        sender="supply@pinevalleyclinics.example", subject="PO 77840 Meridian clinic",
        body="Order for the Meridian clinic attached.",
        customer="Pine Valley Clinics", po="77840", order_date="2026-10-29", requested="2026-11-12",
        bill_to=("Pine Valley Clinics", ["Accounts Payable", "2100 Ridge Rd"], "Boise", "ID", "83702"),
        ship_to=("Pine Valley Clinics - Meridian", ["77 Fairview Ave"], "Meridian", "ID", "83642"),
        ship_via="FedEx Ground", carrier_account="FedEx 2231-9984-1", instructions=None,
        lines=[("PVC-GZ-4", "Gauze 4x4", 12, "PK", 2.95), ("PVC-IVK", "IV start kit", 1, "CS", 195.00)],
        expect=dict(customer_id="C10078", ship_to_id="ST-78-02", status="check", flags=["item_fuzzy_match"]),
    ),
    dict(
        id="12-harborpoint-HP33027", layout="corporate", render="clean",
        sender="buyer@harborpointmed.example", subject="Purchase Order HP33027",
        body="PO HP33027 attached.",
        customer="Harbor Point Medical Supply", po="HP33027", order_date="2026-10-29", requested="2026-11-18",
        bill_to=("Harbor Point Medical Supply", ["9 Dockside Way"], "Portland", "ME", "04101"),
        ship_to=("Harbor Point Medical Supply DC", ["9 Dockside Way"], "Portland", "ME", "04101"),
        ship_via="LTL - our carrier", carrier_account="Estes acct 0098812", instructions=None,
        lines=[("HP 300-119", "Gloves nitrile large", 10, "CS", 98.00), ("HP 520-001", "Sharps 1qt", 4, "CS", 104.00)],
        expect=dict(customer_id="C10103", ship_to_id="ST-03-01", status="clean", flags=[]),
    ),
]

NOISE = [
    dict(id="n1-cedarridge-invoice", sender="billing@cedarridgedental.example", subject="Invoice INV-20931 from Cedar Ridge Dental",
         body="Attached is invoice INV-20931 for the September equipment loan. Payment due net 30.", pdf="INV-20931.pdf",
         title="INVOICE", lines=["Invoice INV-20931", "Equipment loan, September", "Amount due: $240.00"]),
    dict(id="n2-mesa-quote-request", sender="ops@mesaortho.example", subject="Request for quotation: wrist splints",
         body="Could you send a quote for 200 wrist splints? Spec sheet attached.", pdf="RFQ-splints.pdf",
         title="REQUEST FOR QUOTATION", lines=["Item: wrist splint, universal", "Quantity: 200", "Please quote by 11/05"]),
    dict(id="n3-newsletter", sender="news@medsupplyweekly.example", subject="Med Supply Weekly: October newsletter",
         body="This month: glove prices, freight trends. Unsubscribe at any time.", pdf="newsletter-oct.pdf",
         title="MED SUPPLY WEEKLY", lines=["October issue", "Glove prices steady", "Freight rates up 3%"]),
]

CUSTOMER_PHONE = "Phone 555-0100"


# --------------------------------------------------------------------------- PDF layouts


def corporate(c: canvas.Canvas, o: dict) -> None:
    w, h = letter
    c.setFont("Helvetica-Bold", 16)
    c.drawString(50, h - 60, o["customer"])
    c.setFont("Helvetica", 9)
    bt = o["bill_to"]
    c.drawString(50, h - 74, f"{', '.join(bt[1])}, {bt[2]}, {bt[3]} {bt[4]}  |  {CUSTOMER_PHONE}")
    c.setFont("Helvetica-Bold", 20)
    c.drawRightString(w - 50, h - 62, "PURCHASE ORDER")
    c.setFont("Helvetica", 10)
    c.drawRightString(w - 50, h - 80, f"PO Number: {o['po']}")
    c.drawRightString(w - 50, h - 94, f"Order Date: {_us(o['order_date'])}")
    c.setStrokeColor(Color(0.75, 0.75, 0.78))
    c.line(50, h - 106, w - 50, h - 106)
    y = h - 128
    for label, block in (("VENDOR", [VENDOR, *VENDOR_ADDR]), ("BILL TO", _addr(o["bill_to"])), ("SHIP TO", _addr(o["ship_to"]))):
        x = {"VENDOR": 50, "BILL TO": 230, "SHIP TO": 410}[label]
        c.setFont("Helvetica-Bold", 8)
        c.drawString(x, y, label)
        c.setFont("Helvetica", 9.5)
        for i, text in enumerate(block):
            c.drawString(x, y - 14 - i * 12, text)
    y -= 90
    c.setFont("Helvetica-Bold", 8)
    c.drawString(50, y, "REQUESTED DELIVERY")
    c.drawString(200, y, "SHIP VIA")
    c.drawString(330, y, "CARRIER ACCOUNT")
    c.setFont("Helvetica", 9.5)
    c.drawString(50, y - 13, _us(o["requested"]))
    c.drawString(200, y - 13, o.get("ship_via") or "")
    c.drawString(330, y - 13, o.get("carrier_account") or "")
    y -= 40
    _table(c, y, ["Line", "Our Part #", "Description", "Qty", "UOM", "Unit Price", "Extended"],
           [50, 85, 175, 360, 400, 450, 515], o["lines"], order="part-first")
    if o.get("instructions"):
        c.setFont("Helvetica-Bold", 8)
        c.drawString(50, 150, "SHIPPING INSTRUCTIONS")
        c.setFont("Helvetica", 9.5)
        c.drawString(50, 136, o["instructions"])
    c.setFont("Helvetica", 7.5)
    c.drawString(50, 60, "Please reference the PO number on all invoices and packing slips. Terms: Net 30.")


def orderform(c: canvas.Canvas, o: dict) -> None:
    w, h = letter
    c.setFillColor(Color(0.93, 0.94, 0.96))
    c.rect(0, h - 90, w, 90, stroke=0, fill=1)
    c.setFillColor(black)
    c.setFont("Times-Bold", 22)
    c.drawString(50, h - 55, "ORDER FORM")
    c.setFont("Times-Roman", 11)
    c.drawString(50, h - 74, o["customer"])
    c.drawRightString(w - 50, h - 50, f"P.O. # {o['po']}")
    c.drawRightString(w - 50, h - 66, f"Date {_us(o['order_date'])}")
    c.drawRightString(w - 50, h - 82, f"Needed by {_us(o['requested'])}")
    c.setFont("Times-Roman", 10.5)
    c.drawString(50, h - 120, f"To: {VENDOR}, {VENDOR_ADDR[1]}")
    y = h - 160
    _table(c, y, ["Qty", "Unit", "Item No.", "Description", "Price", "Amount"],
           [50, 95, 140, 250, 450, 510], o["lines"], order="qty-first", font="Times-Roman")
    c.setFont("Times-Bold", 10)
    c.drawString(50, 210, "Ship to:")
    c.setFont("Times-Roman", 10.5)
    for i, text in enumerate(_addr(o["ship_to"])):
        c.drawString(50, 196 - i * 13, text)
    c.drawString(300, 210, f"Ship via: {o.get('ship_via') or ''}")
    if o.get("carrier_account"):
        c.drawString(300, 196, f"Carrier acct: {o['carrier_account']}")
    c.setFont("Times-Italic", 9)
    c.drawString(50, 70, "Questions? Call materials management. Thank you!")


def handwritten(c: canvas.Canvas, o: dict) -> None:
    """A printed blank form, filled in by hand."""
    w, h = letter
    c.setFont("Helvetica-Bold", 15)
    c.drawString(50, h - 60, "SUPPLY ORDER FORM")
    c.setFont("Helvetica", 9)
    c.drawString(50, h - 76, "St. Brigid Rehabilitation Center  |  310 Elm St, Dayton, OH 45402")
    labels = [("Date:", h - 110), ("PO #:", h - 132), ("Ordered by:", h - 154), ("Need by:", h - 176)]
    for label, y in labels:
        c.setFont("Helvetica", 10)
        c.drawString(50, y, label)
        c.line(120, y - 3, 320, y - 3)
    c.setFont("Helvetica", 10)
    c.drawString(350, h - 110, "Vendor: Alder Medical")
    header_y = h - 220
    cols = [50, 140, 330, 400, 470]
    for x, label in zip(cols, ["Item #", "Description", "Qty", "Unit", "Price"]):
        c.drawString(x, header_y, label)
    for i in range(10):
        c.line(50, header_y - 10 - i * 26, w - 50, header_y - 10 - i * 26)
    c.drawString(50, 150, "Notes:")
    c.line(95, 147, w - 50, 147)

    c.setFont(HAND, 13)
    c.setFillColor(Color(0.08, 0.15, 0.45))
    c.drawString(126, h - 108, "10/29/26")
    c.drawString(126, h - 152, "Ann K.")
    c.drawString(126, h - 174, "Nov 6")
    for i, (part, desc, qty, unit, price) in enumerate(o["lines"]):
        y = header_y - 30 - i * 26
        jitter = random.uniform(-2, 2)
        c.drawString(cols[0] + 2, y + jitter, part)
        c.drawString(cols[1] + 2, y - jitter, desc)
        c.drawString(cols[2] + 6, y + jitter, f"{qty:g}")
        c.drawString(cols[3] + 2, y, unit)
        c.drawString(cols[4] + 2, y - jitter, f"{price:.2f}")
    c.drawString(100, 150, o["instructions"])


def pinevalley(c: canvas.Canvas, o: dict) -> None:
    """Fax cover sheet, two order pages, a terms page."""
    w, h = letter
    c.setFont("Helvetica-Bold", 26)
    c.drawString(50, h - 80, "FAX COVER SHEET")
    c.setFont("Helvetica", 12)
    rows = [("To:", "Alder Medical Products - Order Desk"), ("From:", "Pine Valley Clinics, Central Supply"),
            ("Date:", _us(o["order_date"])), ("Number of pages:", "4 (including cover)"),
            ("Re:", f"Purchase order {o['po']}")]
    for i, (k, v) in enumerate(rows):
        c.drawString(50, h - 140 - i * 24, k)
        c.drawString(190, h - 140 - i * 24, v)
    c.setFont("Helvetica-Oblique", 10)
    c.drawString(50, h - 300, "CONFIDENTIAL: intended only for the addressee. If received in error, please call us.")
    c.showPage()

    for page, chunk in ((1, o["lines"][:3]), (2, o["lines"][3:])):
        c.setFont("Helvetica-Bold", 14)
        c.drawString(50, h - 60, "Pine Valley Clinics")
        c.setFont("Helvetica-Bold", 16)
        c.drawRightString(w - 50, h - 60, f"PURCHASE ORDER {o['po']}")
        c.setFont("Helvetica", 9.5)
        c.drawRightString(w - 50, h - 76, f"Page {page} of 2   Order date {_us(o['order_date'])}   Required {_us(o['requested'])}")
        if page == 1:
            c.drawString(50, h - 100, "Ship to: " + ", ".join(_addr(o["ship_to"])))
            c.drawString(50, h - 114, "Bill to: " + ", ".join(_addr(o["bill_to"])))
            c.drawString(50, h - 128, f"Ship via: {o['ship_via']}   Carrier account: {o['carrier_account']}")
            c.drawString(50, h - 142, f"Instructions: {o['instructions']}")
        start = 1 if page == 1 else 4
        _table(c, h - 175, ["Ln", "Item", "Description", "Qty", "U/M", "Price", "Total"],
               [50, 80, 165, 360, 400, 450, 515], chunk, order="part-first", first_line=start)
        c.showPage()

    c.setFont("Helvetica-Bold", 13)
    c.drawString(50, h - 60, "TERMS AND CONDITIONS OF PURCHASE")
    c.setFont("Helvetica", 8.2)
    terms = (
        "1. Acceptance. This purchase order is an offer to buy and becomes binding on acceptance by shipment or written confirmation. "
        "2. Warranty. Seller warrants that goods conform to specifications and are free from defects in material and workmanship. "
        "3. Indemnification. Seller shall indemnify Buyer against claims arising from defective goods. "
        "4. Force majeure. Neither party is liable for delays caused by events beyond its reasonable control. "
        "5. Governing law. This order is governed by the laws of the State of Idaho. "
        "6. Changes. Buyer may change quantities or delivery dates by written notice before shipment. "
    ) * 3
    _wrap(c, terms, 50, h - 90, 95, 11)


def _table(c, y, headers, xs, lines, order, font="Helvetica", first_line=1):
    c.setFont(f"{font}-Bold" if font != "Times-Roman" else "Times-Bold", 8.5)
    for x, label in zip(xs, headers):
        c.drawString(x, y, label)
    c.setStrokeColor(Color(0.8, 0.8, 0.83))
    c.line(50, y - 5, 562, y - 5)
    c.setFont(font, 9.5)
    total = 0.0
    for i, (part, desc, qty, unit, price) in enumerate(lines):
        row = y - 22 - i * 18
        ext = qty * price
        total += ext
        if order == "part-first":
            values = [str(first_line + i), part, desc[:34], f"{qty:g}", unit, f"{price:,.2f}", f"{ext:,.2f}"]
        else:
            values = [f"{qty:g}", unit, part, desc[:34], f"{price:,.2f}", f"{ext:,.2f}"]
        for x, v in zip(xs, values):
            c.drawString(x, row, v)
    c.line(50, y - 22 - len(lines) * 18 + 8, 562, y - 22 - len(lines) * 18 + 8)
    c.setFont(f"{font}-Bold" if font != "Times-Roman" else "Times-Bold", 9.5)
    c.drawRightString(562, y - 22 - len(lines) * 18 - 8, f"Total {total:,.2f}")


def _wrap(c, text, x, y, width_chars, leading):
    words, line = text.split(), ""
    for word in words:
        if len(line) + len(word) + 1 > width_chars:
            c.drawString(x, y, line)
            y -= leading
            line = word
        else:
            line = f"{line} {word}".strip()
    if line:
        c.drawString(x, y, line)


def _addr(a) -> list[str]:
    name, lines, city, state, postal = a
    return [name, *lines, f"{city}, {state} {postal}"]


def _us(iso: str) -> str:
    return datetime.strptime(iso, "%Y-%m-%d").strftime("%m/%d/%Y")


LAYOUTS = {"corporate": corporate, "orderform": orderform, "handwritten": handwritten, "pinevalley": pinevalley}


def render_clean(o: dict) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.setTitle(f"PO {o.get('po') or 'order form'}")
    LAYOUTS[o["layout"]](c, o)
    c.showPage()
    c.save()
    return _drop_blank_trailing(buf.getvalue())


def _drop_blank_trailing(data: bytes) -> bytes:
    doc = pymupdf.open(stream=data, filetype="pdf")
    while len(doc) > 1 and not doc[-1].get_text().strip() and not doc[-1].get_drawings():
        doc.delete_page(-1)
    return doc.tobytes()


def render_scanned(o: dict, style: str, rotate: int = 0) -> bytes:
    """Rasterize the clean layout, age it like a scan or a fax, and rebuild an image-only PDF."""
    clean = pymupdf.open(stream=render_clean(o), filetype="pdf")
    out = pymupdf.open()
    for page in clean:
        pix = page.get_pixmap(dpi=200, colorspace=pymupdf.csGRAY)
        img = Image.frombytes("L", (pix.width, pix.height), pix.samples)
        img = _age(img, style)
        if rotate:
            img = img.rotate(rotate, expand=True, fillcolor=245)  # counter-clockwise, as a careless scan
        buf = io.BytesIO()
        if style == "fax":
            img.convert("1").save(buf, format="PNG")  # two-tone, compresses well
        else:
            img.save(buf, format="JPEG", quality=72)  # scanners write JPEG; noise defeats PNG
        w_pt, h_pt = img.width * 72 / 200, img.height * 72 / 200
        new = out.new_page(width=w_pt, height=h_pt)
        new.insert_image(new.rect, stream=buf.getvalue())
    return out.tobytes(deflate=True)


def _age(img: Image.Image, style: str) -> Image.Image:
    img = img.rotate(random.uniform(-1.2, 1.2), expand=False, fillcolor=255, resample=Image.BICUBIC)
    arr = np.asarray(img, dtype=np.float32)
    if style == "fax":
        arr = np.asarray(img.resize((img.width // 2, img.height // 2)).resize(img.size), dtype=np.float32)
        arr += np.random.normal(0, 28, arr.shape)
        arr = np.where(arr < 150, 0, 255).astype(np.float32)
        speckle = np.random.random(arr.shape) < 0.0025
        arr[speckle] = 0
    else:
        arr = arr * 0.92 + 8 + np.random.normal(0, 7, arr.shape)
    img = Image.fromarray(np.clip(arr, 0, 255).astype(np.uint8))
    return img.filter(ImageFilter.GaussianBlur(0.5 if style == "fax" else 0.7))


def render_noise(n: dict) -> bytes:
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    w, h = letter
    c.setFont("Helvetica-Bold", 20)
    c.drawString(50, h - 70, n["title"])
    c.setFont("Helvetica", 11)
    for i, line in enumerate(n["lines"]):
        c.drawString(50, h - 110 - i * 18, line)
    c.showPage()
    c.save()
    return buf.getvalue()


# --------------------------------------------------------------------------- email, truth, mock


def make_email(sender: str, subject: str, body: str, attachments: list[tuple[str, bytes]], when: datetime) -> bytes:
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = VENDOR_EMAIL
    msg["Subject"] = subject
    msg["Date"] = format_datetime(when)
    msg.set_content(body)
    for name, data in attachments:
        msg.add_attachment(data, maintype="application", subtype="pdf", filename=name)
    return msg.as_bytes()


def truth_for(o: dict) -> dict:
    return {
        "file": f"{o['id']}.pdf",
        "po_number": o["po"],
        "customer_name": o["customer"],
        "order_date": o["order_date"],
        "requested_date": o["requested"],
        "ship_to_postal_code": o["ship_to"][4],
        "carrier_account": o.get("carrier_account"),
        "lines": [{"customer_part": p, "quantity": q, "unit_of_measure": u, "unit_price": pr} for p, _, q, u, pr in o["lines"]],
        "expected": o["expect"],
    }


def mock_for(o: dict) -> dict:
    """The response a careful model would give, written by hand (here, generated from the truth)."""
    conf = o.get("mock_conf", {})
    scanned = o["render"] != "clean"
    base = 0.9 if scanned else 0.98

    def tf(value, page=1, c=None):
        return {"value": value, "confidence": c if c is not None else base, "page": page if value is not None else None}

    def nf(value, page=1, c=None):
        return {"value": value, "confidence": c if c is not None else base, "page": page}

    def addr(a, page=1):
        name, lines, city, state, postal = a
        return {"name": name, "lines": lines, "city": city, "state": state, "postal_code": postal, "country": "US",
                "confidence": base, "page": page}

    first_order_page = 2 if o["layout"] == "pinevalley" else 1
    lines = []
    for i, (part, desc, qty, unit, price) in enumerate(o["lines"], start=1):
        page = first_order_page + (1 if o["layout"] == "pinevalley" and i > 3 else 0)
        lines.append({
            "line_number": i,
            "customer_part": tf(part, page, conf.get(("lines", i, "customer_part"))),
            "description": tf(desc, page),
            "quantity": nf(qty, page, conf.get(("lines", i, "quantity"))),
            "unit_of_measure": tf(unit, page, conf.get(("lines", i, "unit_of_measure"))),
            "unit_price": nf(price, page, conf.get(("lines", i, "unit_price"))),
        })
    pages = [{"page": 1, "role": "order", "rotation_seen": 0}]
    if o["layout"] == "pinevalley":
        pages = [{"page": 1, "role": "cover", "rotation_seen": 0}, {"page": 2, "role": "order", "rotation_seen": 0},
                 {"page": 3, "role": "order", "rotation_seen": 0}, {"page": 4, "role": "terms", "rotation_seen": 0}]
    notes = []
    if o["layout"] == "handwritten":
        notes.append("Handwritten form; the PO number box is empty.")
    return {
        "_note": "Hand-written mock response for the offline demo, generated by scripts/make_samples.py. Not real model output.",
        "is_purchase_order": True,
        "po_number": tf(o["po"], first_order_page),
        "customer_name": tf(o["customer"], first_order_page),
        "order_date": tf(o["order_date"], first_order_page),
        "requested_date": tf(o["requested"], first_order_page),
        "bill_to": addr(o["bill_to"], first_order_page),
        "ship_to": addr(o["ship_to"], first_order_page),
        "shipping_instructions": tf(o.get("instructions"), first_order_page),
        "carrier": tf(o.get("ship_via"), first_order_page),
        "carrier_account": tf(o.get("carrier_account"), first_order_page),
        "lines": lines,
        "pages": pages,
        "notes": notes,
    }


def main() -> None:
    write_erp()
    inbox = SAMPLES / "inbox"
    for folder in (inbox, SAMPLES / "truth", SAMPLES / "mock_responses", SAMPLES / "pdf"):
        folder.mkdir(parents=True, exist_ok=True)
        for old in folder.glob("*"):
            old.unlink()

    by_id = {o["id"]: o for o in ORDERS}
    when = datetime(2026, 10, 29, 7, 2, tzinfo=timezone(timedelta(hours=-5)))
    for o in ORDERS:
        if "same_as" in o:
            source = by_id[o["same_as"]]
            o.update({k: v for k, v in source.items() if k not in ("id", "subject", "body", "expect", "same_as")})
        if o["render"] == "clean":
            pdf = render_clean(o)
        else:
            pdf = render_scanned(o, "fax" if o["render"] == "fax" else "scan", o.get("rotate", 0))
        name = f"{o['id']}.pdf"
        (SAMPLES / "pdf" / name).write_bytes(pdf)
        (inbox / f"{o['id']}.eml").write_bytes(make_email(o["sender"], o["subject"], o["body"], [(name, pdf)], when))
        (SAMPLES / "truth" / f"{o['id']}.json").write_text(json.dumps(truth_for(o), indent=2))
        (SAMPLES / "mock_responses" / f"{o['id']}.json").write_text(json.dumps(mock_for(o), indent=2))
        when += timedelta(minutes=random.randint(4, 40))

    for n in NOISE:
        pdf = render_noise(n)
        (inbox / f"{n['id']}.eml").write_bytes(make_email(n["sender"], n["subject"], n["body"], [(n["pdf"], pdf)], when))
        when += timedelta(minutes=random.randint(4, 40))
    print(f"wrote {len(ORDERS)} orders and {len(NOISE)} non-order emails to {SAMPLES}")


if __name__ == "__main__":
    main()
