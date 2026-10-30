"""Page preparation: render, straighten and sort the pages of an incoming PDF.

Purchase orders arrive as clean system PDFs, faxes, phone photos and scans fed in
sideways or upside down. Before anything is sent to a model, every page is:

1. rendered to an image (the PDF's own /Rotate is honoured by the renderer),
2. checked for a usable text layer,
3. straightened when its content is rotated 90, 180 or 270 degrees,
4. given a role: order, cover sheet, terms page, or unknown.

Orientation comes from the text layer when there is one (the direction of the text
runs), and from the pixels when there is not: text lines make the row profile of an
upright page much spikier than its column profile, and Latin text has more ascenders
than descenders, which tells upright from upside down. When neither signal is clear
the page is kept as is and flagged, and the vision model reads it anyway.
"""

from __future__ import annotations

import io
import math
import re
from dataclasses import dataclass, field

import numpy as np
import pymupdf
from PIL import Image

RENDER_DPI = 150
MAX_LONG_EDGE = 2000  # keeps image tokens per page bounded
UNCERTAIN = 0.75  # below this, a pixel-based orientation is flagged for a glance

COVER_PATTERNS = [
    r"\bfax\s+cover\b",
    r"\bcover\s+sheet\b",
    r"\bnumber\s+of\s+pages\b",
    r"\bpages?\s*\(?including\s+cover\)?",
    r"\btransmittal\b",
]
TERMS_PATTERNS = [
    r"\bterms\s+and\s+conditions\b",
    r"\bconditions\s+of\s+purchase\b",
    r"\bindemnif",
    r"\bgoverning\s+law\b",
    r"\bwarrant(y|ies)\b",
    r"\bforce\s+majeure\b",
]
ORDER_PATTERNS = [
    r"\bpurchase\s+order\b",
    r"\bp\.?\s?o\.?\s*(#|no\.?|number)",
    r"\bqty\b|\bquantity\b",
    r"\bunit\s+price\b|\bprice\b",
    r"\bship\s*to\b",
    r"\bitem\b|\bpart\b",
]


@dataclass
class PreparedPage:
    number: int  # 1-based, as in the original file
    image: Image.Image  # upright
    text: str
    has_text_layer: bool
    text_quality: float
    rotation_applied: int  # degrees clockwise applied to make the page upright
    rotation_source: str  # pdf | text | pixels | none
    rotation_confidence: float
    role: str  # order | cover | terms | unknown
    role_reason: str = ""

    def png_bytes(self, max_long_edge: int = MAX_LONG_EDGE) -> bytes:
        img = _limit(self.image, max_long_edge)
        buf = io.BytesIO()
        img.save(buf, format="PNG", optimize=True)
        return buf.getvalue()


@dataclass
class PreparedDocument:
    filename: str
    pages: list[PreparedPage] = field(default_factory=list)

    @property
    def order_pages(self) -> list[PreparedPage]:
        """Pages to send to extraction. Unknown pages go too: better a page too many than a lost line."""
        return [p for p in self.pages if p.role in ("order", "unknown")]

    @property
    def uncertain_orientation(self) -> list[int]:
        return [p.number for p in self.pages if p.rotation_source == "pixels" and p.rotation_confidence < UNCERTAIN]


def prepare_pdf(data: bytes, filename: str = "document.pdf") -> PreparedDocument:
    doc = pymupdf.open(stream=data, filetype="pdf")
    prepared = PreparedDocument(filename=filename)
    for index, page in enumerate(doc):
        prepared.pages.append(_prepare_page(page, index + 1))
    doc.close()
    _resolve_roles(prepared)
    return prepared


def _prepare_page(page: pymupdf.Page, number: int) -> PreparedPage:
    pdf_rotation = page.rotation  # applied by the renderer below
    pix = page.get_pixmap(dpi=RENDER_DPI)
    image = Image.frombytes("RGB", (pix.width, pix.height), pix.samples)

    text = page.get_text("text")
    quality = text_quality(text)
    has_text = quality >= 0.5

    rotation, source, confidence = 0, "none", 1.0
    if has_text:
        rotation = text_rotation(page)
        source = "text" if rotation else ("pdf" if pdf_rotation else "none")
    else:
        rotation, confidence = detect_rotation(image)
        source = "pixels" if rotation or confidence < UNCERTAIN else ("pdf" if pdf_rotation else "none")
    if rotation:
        image = rotate_clockwise(image, rotation)

    return PreparedPage(
        number=number,
        image=image,
        text=text if has_text else "",
        has_text_layer=has_text,
        text_quality=quality,
        rotation_applied=rotation,
        rotation_source=source,
        rotation_confidence=round(confidence, 3),
        role="unknown",
    )


# --------------------------------------------------------------------------- text layer


def text_quality(text: str) -> float:
    """0 to 1. Scanned PDFs often carry an empty or garbage text layer; only trust a real one."""
    stripped = text.strip()
    if len(stripped) < 40:
        return 0.0
    words = re.findall(r"[A-Za-z]{2,}", stripped)
    if len(words) < 8:
        return 0.2
    printable = sum(ch.isprintable() or ch in "\n\t" for ch in stripped) / len(stripped)
    wordish = sum(len(w) for w in words) / max(1, len(re.sub(r"\s", "", stripped)))
    return round(min(1.0, 0.5 * printable + 0.8 * wordish), 3)


def text_rotation(page: pymupdf.Page) -> int:
    """Clockwise degrees that make the text upright, from the direction of the text runs.

    Runs are measured in the rotated page space the renderer already applied, so the
    answer is relative to the rendered image.
    """
    votes: dict[int, int] = {0: 0, 90: 0, 180: 0, 270: 0}
    matrix = page.rotation_matrix
    for block in page.get_text("dict")["blocks"]:
        for line in block.get("lines", []):
            dx, dy = line["dir"]
            vec = pymupdf.Point(dx, dy) * matrix - pymupdf.Point(0, 0) * matrix
            angle = math.degrees(math.atan2(vec.y, vec.x)) % 360
            nearest = int(round(angle / 90.0) * 90) % 360
            chars = sum(len(span["text"]) for span in line["spans"])
            votes[nearest] += chars
    reading = max(votes, key=votes.get)
    # text running at 90 degrees (downwards) needs a 270 degree clockwise turn, and so on
    return (360 - reading) % 360


# --------------------------------------------------------------------------- pixels


def detect_rotation(image: Image.Image) -> tuple[int, float]:
    """Clockwise rotation that makes a scanned page upright, with a 0 to 1 confidence.

    Two questions, answered separately. Is the text horizontal or vertical? The row profile of
    upright text alternates between lines and the gaps between them, so its coefficient of
    variation is several times higher than the column profile's. Then, which way is up? Latin
    text has more ink above the x-height band (capitals, b d f h k l t) than below it (g j p q y);
    each text line votes. A sideways page is always turned; an upright-looking page is only
    flipped when the vote clearly says upside down.
    """
    ink = _ink(image)
    if ink.mean() < 0.002:
        return 0, 0.0  # blank page

    upright, sideways = _line_spikiness(ink), _line_spikiness(ink.T)
    if sideways > upright * 1.15:
        score = _direction_score(np.rot90(ink, k=-1))
        rotation = 90 if score >= 0 else 270
    elif upright > sideways * 1.15:
        score = _direction_score(ink)
        rotation = 180 if score < -0.12 else 0
    else:
        return 0, 0.3  # no clear text direction, leave it to the model
    return rotation, round(min(1.0, 0.5 + abs(score) * 2), 3)


def _ink(image: Image.Image) -> np.ndarray:
    gray = np.asarray(_limit(image, 1400).convert("L"), dtype=np.float32) / 255.0
    threshold = min(0.6, float(np.percentile(gray, 50)) - 0.15)
    return (gray < threshold).astype(np.float32)


def _line_spikiness(ink: np.ndarray) -> float:
    """How strongly ink concentrates into horizontal bands (text lines).

    The coefficient of variation of the row profile: rows alternate between text and the white
    space between lines, so an upright page scores several times higher than the same page on
    its side, where every row cuts across many lines.
    """
    rows = ink.mean(axis=1)
    mean = rows.mean()
    if mean == 0:
        return 0.0
    return float(rows.std() / mean)


def _remove_rules(ink: np.ndarray, min_run: int) -> np.ndarray:
    """Erase long horizontal runs (table rules, form lines, underlines) so only letters remain."""
    cleaned = ink.copy()
    for y in range(ink.shape[0]):
        row = ink[y]
        if row.sum() < min_run:
            continue
        padded = np.concatenate(([0], row, [0]))
        edges = np.diff(padded)
        starts, ends = np.nonzero(edges == 1)[0], np.nonzero(edges == -1)[0]
        for start, end in zip(starts, ends):
            if end - start >= min_run:
                cleaned[y, start:end] = 0
    return cleaned


def _direction_score(ink: np.ndarray) -> float:
    """-1 to 1. Positive when text lines carry more ink above their x-height band than below it."""
    ink = _remove_rules(ink, max(40, ink.shape[1] // 25))
    rows = ink.mean(axis=1)
    bands = [(t, b) for t, b in _bands(rows, 0.08) if b - t >= 6]
    if not bands:
        return 0.0
    median = float(np.median([b - t for t, b in bands]))
    signs, ratios = [], []
    for top, bottom in bands:
        if not (0.6 * median <= bottom - top <= 1.6 * median):
            continue  # titles and merged lines distort the shape of a line
        band = rows[top:bottom]
        core = np.nonzero(band > band.max() * 0.5)[0]
        above, below = band[: core[0]].sum(), band[core[-1] + 1 :].sum()
        if above + below < 0.05 * band.sum():
            continue  # all capitals or digits: no vote
        signs.append(np.sign(above - below))
        ratios.append((above - below) / (above + below))
    if len(signs) < 3:
        return 0.0
    return float(0.5 * np.mean(signs) + 0.5 * np.mean(ratios))


def _bands(rows: np.ndarray, threshold: float) -> list[tuple[int, int]]:
    active = rows > rows.max() * threshold
    bands, start = [], None
    for i, on in enumerate(active):
        if on and start is None:
            start = i
        elif not on and start is not None:
            bands.append((start, i))
            start = None
    if start is not None:
        bands.append((start, len(rows)))
    return bands


def rotate_clockwise(image: Image.Image, degrees: int) -> Image.Image:
    if degrees % 360 == 0:
        return image
    return image.rotate(-degrees, expand=True, fillcolor="white")


def _limit(image: Image.Image, max_long_edge: int) -> Image.Image:
    long_edge = max(image.size)
    if long_edge <= max_long_edge:
        return image
    scale = max_long_edge / long_edge
    return image.resize((round(image.width * scale), round(image.height * scale)), Image.LANCZOS)


# --------------------------------------------------------------------------- roles


def classify_text(text: str) -> tuple[str, str]:
    lowered = text.lower()
    cover = sum(bool(re.search(p, lowered)) for p in COVER_PATTERNS)
    terms = sum(bool(re.search(p, lowered)) for p in TERMS_PATTERNS)
    order = sum(bool(re.search(p, lowered)) for p in ORDER_PATTERNS)
    money = len(re.findall(r"\$?\d{1,6}\.\d{2}\b", text))
    if money >= 2:
        order += 2
    if cover >= 1 and order <= 2:
        return "cover", f"{cover} cover-sheet cues, {order} order cues"
    if terms >= 2 and money < 2:
        return "terms", f"{terms} terms cues, no prices"
    if order >= 2:
        return "order", f"{order} order cues"
    return "unknown", "not enough text to tell"


def _resolve_roles(doc: PreparedDocument) -> None:
    for page in doc.pages:
        if page.has_text_layer:
            page.role, page.role_reason = classify_text(page.text)
        else:
            page.role, page.role_reason = "unknown", "image only, the model decides"
    if doc.pages and not any(p.role in ("order", "unknown") for p in doc.pages):
        # never drop everything: if every page looked like a cover or terms, send them all
        for page in doc.pages:
            page.role, page.role_reason = "unknown", "no page looked like an order"
