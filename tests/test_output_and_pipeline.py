import csv
import io
import json
from pathlib import Path

import pytest

from orderline.cost import PRICES_PER_MTOK, estimate, image_tokens, measured_cost
from orderline.erp import ErpData
from orderline.evaluate import score_order
from orderline.extract.mock import MockExtractor
from orderline.mail.folder import FolderMailSource
from orderline.models import ExtractedOrder
from orderline.output import CsvSpec, render_csv, review_status, write_order
from orderline.pipeline import run_batch
from orderline.prepare import SeenOrders, prepare_order
from orderline.report import render_report

from .conftest import ROOT, SAMPLES, message, result

SPEC = CsvSpec.load(ROOT / "config" / "columns.yaml")


@pytest.fixture(scope="module")
def batch(tmp_path_factory):
    out = tmp_path_factory.mktemp("demo")
    return run_batch(
        FolderMailSource(SAMPLES / "inbox"),
        ErpData.load(ROOT / "data" / "erp"),
        MockExtractor(SAMPLES / "mock_responses"),
        SPEC,
        out,
        SeenOrders(out / "seen.json"),
    )


def test_csv_has_one_row_per_line_with_header(erp, northwind_doc, order_payload):
    order = prepare_order(erp, message(), northwind_doc, result(order_payload()), SeenOrders())
    rows = list(csv.DictReader(io.StringIO(render_csv(order, SPEC))))
    assert len(rows) == 4
    assert rows[0]["CUSTOMER_NO"] == "C10021" and rows[0]["PO_NUMBER"] == "4500884512"
    assert rows[0]["REQUESTED_DATE"] == "11/12/2026"
    assert rows[0]["ITEM_NO"] == "MS-GLV-NIT-M" and rows[0]["QTY"] == "20" and rows[0]["UNIT_PRICE"] == "11.25"
    assert rows[0]["REVIEW_STATUS"] == "clean" and rows[0]["REVIEW_FLAGS"] == ""


def test_blocked_order_is_written_with_its_status(erp, northwind_doc, order_payload, tmp_path):
    payload = order_payload()
    payload["po_number"]["value"] = None
    order = prepare_order(erp, message(), northwind_doc, result(payload), SeenOrders())
    csv_path, sidecar = write_order(order, SPEC, tmp_path)
    assert csv_path.name.startswith("C10021_NOPO_")
    rows = list(csv.DictReader(csv_path.open()))
    assert {r["REVIEW_STATUS"] for r in rows} == {"blocked"}
    data = json.loads(sidecar.read_text())
    assert data["review_status"] == "blocked"
    assert data["flags"][0]["code"] == "missing_po_number"


def test_column_spec_is_configurable(erp, northwind_doc, order_payload, tmp_path):
    spec_file = tmp_path / "spec.yaml"
    spec_file.write_text(
        "filename: '{po_number}.txt'\ndelimiter: ';'\nheader: false\ndate_format: '%Y%m%d'\n"
        "columns:\n  - {name: PO, source: order.po_number}\n  - {name: D, source: order.requested_date}\n"
        "  - {name: ITEM, source: line.item_number}\n"
    )
    order = prepare_order(erp, message(), northwind_doc, result(order_payload()), SeenOrders())
    text = render_csv(order, CsvSpec.load(spec_file))
    assert text.splitlines()[0] == "4500884512;20261112;MS-GLV-NIT-M"


def test_filename_is_sanitized(erp, northwind_doc, order_payload, tmp_path):
    payload = order_payload()
    payload["po_number"]["value"] = "PO 12/34 #A"
    order = prepare_order(erp, message(), northwind_doc, result(payload), SeenOrders())
    csv_path, _ = write_order(order, SPEC, tmp_path)
    assert "/" not in csv_path.name and " " not in csv_path.name


EXPECTED = {json.loads(p.read_text())["file"]: json.loads(p.read_text())["expected"] for p in (SAMPLES / "truth").glob("*.json")}


@pytest.mark.parametrize("filename", sorted(EXPECTED))
def test_demo_batch_matches_ground_truth(batch, filename):
    want = EXPECTED[filename]
    processed = next(p for p in batch.orders if p.order.source_file == filename)
    order = processed.order
    assert review_status(order) == want["status"]
    assert order.customer_id == want["customer_id"]
    assert order.ship_to.ship_to_id == want["ship_to_id"]
    assert {f.code.value for f in order.flags if f.severity.value != "info"} == set(want["flags"])


def test_demo_batch_skips_the_three_non_orders(batch):
    assert len(batch.orders) == 12
    assert sorted(s.message_id for s in batch.skipped) == [
        "n1-cedarridge-invoice.eml", "n2-mesa-quote-request.eml", "n3-newsletter.eml"]


def test_review_report_renders_every_order(batch, tmp_path):
    html = render_report(batch, tmp_path, "mock")
    assert html.count('<article class="order">') == 12
    assert "No PO number on the document" in html
    assert "data:image/png;base64," in html


def test_cost_estimate_orders_models_by_price():
    per_1000 = {m: estimate(m).usd_per_1000 for m in PRICES_PER_MTOK}
    assert per_1000["claude-opus-5-5"] > per_1000["claude-sonnet-5-5"] > per_1000["claude-haiku-5-5"] > 0
    assert image_tokens(10_000, 10_000) == 4784  # capped
    assert measured_cost("claude-opus-5-5", 1_000_000, 0, 1000) == pytest.approx(4.0 * 1000 / 1000)


def test_scoring_against_truth(mock_payloads):
    truth = json.loads((SAMPLES / "truth" / "01-northwind-4500884512.json").read_text())
    perfect = score_order(ExtractedOrder.model_validate(mock_payloads["01-northwind-4500884512"]), truth)
    assert perfect.accuracy == 1.0
    wrong = dict(mock_payloads["01-northwind-4500884512"])
    wrong["lines"] = wrong["lines"][:3]
    s = score_order(ExtractedOrder.model_validate(wrong), truth)
    assert s.accuracy < 1.0 and any("line 4" in m for m in s.misses)
