import io

import pymupdf
import pytest
from PIL import Image
from reportlab.lib.pagesizes import letter
from reportlab.pdfgen import canvas

from orderline.pages import classify_text, detect_rotation, prepare_pdf, rotate_clockwise, text_quality


def test_text_quality_rejects_empty_and_garbage():
    assert text_quality("") == 0.0
    assert text_quality("§§ ¶¶ 12 34 ## ~~ " * 3) < 0.5
    assert text_quality("Purchase order 4500884512 for nitrile gloves, syringes and masks shipped to Bellevue.") >= 0.5


@pytest.mark.parametrize(
    "text, role",
    [
        ("FAX COVER SHEET\nTo: Order desk\nNumber of pages: 4 (including cover)", "cover"),
        ("TERMS AND CONDITIONS OF PURCHASE. Warranty. Indemnification. Governing law. Force majeure.", "terms"),
        ("PURCHASE ORDER 77812\nShip to: Boise\nItem Qty Price\nPVC-GL-M 40 BX 11.80 472.00", "order"),
        ("Hello", "unknown"),
    ],
)
def test_classify_text_roles(text, role):
    assert classify_text(text)[0] == role


def test_multi_page_fax_skips_cover_and_terms(sample_pdf):
    doc = prepare_pdf(sample_pdf("03-pinevalley-77812"), "03.pdf")
    assert [p.role for p in doc.pages] == ["cover", "order", "order", "terms"]
    assert [p.number for p in doc.order_pages] == [2, 3]


def test_clean_pdf_uses_text_layer(northwind_doc):
    page = northwind_doc.pages[0]
    assert page.has_text_layer and page.role == "order"
    assert "4500884512" in page.text
    assert page.rotation_applied == 0


@pytest.mark.parametrize("sample", ["05-stbrigid-handwritten", "06-mesa-fax-MOP-1187"])
def test_scans_have_no_text_layer_and_go_to_vision(sample, sample_pdf):
    doc = prepare_pdf(sample_pdf(sample), f"{sample}.pdf")
    assert not doc.pages[0].has_text_layer
    assert doc.pages[0].role == "unknown"  # the model decides
    assert doc.order_pages == doc.pages


@pytest.mark.parametrize(
    "sample, expected",
    [("07-cedarridge-sideways-CRD-0419", 90), ("08-bayview-upsidedown-BV-311", 180), ("06-mesa-fax-MOP-1187", 0)],
)
def test_scanned_pages_are_straightened(sample, expected, sample_pdf):
    page = prepare_pdf(sample_pdf(sample), f"{sample}.pdf").pages[0]
    assert page.rotation_applied == expected
    assert page.image.width < page.image.height  # upright letter page


def _page_image(sample_pdf, sample: str) -> Image.Image:
    page = pymupdf.open(stream=sample_pdf(sample), filetype="pdf")[0]
    pix = page.get_pixmap(dpi=150)
    return Image.frombytes("RGB", (pix.width, pix.height), pix.samples)


@pytest.mark.parametrize("ccw", [0, 90, 180, 270])
@pytest.mark.parametrize("sample", ["05-stbrigid-handwritten", "06-mesa-fax-MOP-1187"])
def test_detect_rotation_in_all_four_directions(sample, ccw, sample_pdf):
    upright = _page_image(sample_pdf, sample)
    turned = upright.rotate(ccw, expand=True, fillcolor="white")
    rotation, confidence = detect_rotation(turned)
    assert rotation == ccw  # turning it back clockwise by the same amount
    assert confidence >= 0.75


def test_blank_page_is_left_alone():
    rotation, confidence = detect_rotation(Image.new("RGB", (1200, 1600), "white"))
    assert (rotation, confidence) == (0, 0.0)


def test_rotate_clockwise_swaps_dimensions():
    img = Image.new("RGB", (100, 200), "white")
    assert rotate_clockwise(img, 90).size == (200, 100)
    assert rotate_clockwise(img, 0) is img


def test_text_layer_rotation_from_text_direction():
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=letter)
    c.translate(300, 100)
    c.rotate(90)  # text runs bottom to top
    for i in range(12):
        c.drawString(0, -14 * i, f"Purchase order line {i} nitrile gloves medium box quantity price")
    c.save()
    page = prepare_pdf(buf.getvalue(), "rotated.pdf").pages[0]
    assert page.has_text_layer
    assert page.rotation_source == "text"
    assert page.rotation_applied == 90
