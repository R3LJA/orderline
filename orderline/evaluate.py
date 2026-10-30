"""Field-level scoring of an extraction against ground truth.

Used by ``evals/run_eval.py`` with the real model. Scores what the model read, before any ERP
matching: header fields, and for each line the part number, quantity, unit and price. Lines are
paired by position; a missing or extra line counts every field of it as wrong.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .erp import normalize_part
from .models import ExtractedOrder

HEADER_FIELDS = ("po_number", "customer_name", "requested_date", "ship_to_postal_code", "carrier_account")
LINE_FIELDS = ("customer_part", "quantity", "unit_of_measure", "unit_price")


@dataclass
class Score:
    correct: int = 0
    total: int = 0
    misses: list[str] = field(default_factory=list)

    @property
    def accuracy(self) -> float:
        return self.correct / self.total if self.total else 1.0

    def check(self, name: str, ok: bool, got, want) -> None:
        self.total += 1
        if ok:
            self.correct += 1
        else:
            self.misses.append(f"{name}: got {got!r}, want {want!r}")


def score_order(extracted: ExtractedOrder, truth: dict) -> Score:
    s = Score()
    got = {
        "po_number": extracted.po_number.value,
        "customer_name": extracted.customer_name.value,
        "requested_date": extracted.requested_date.value,
        "ship_to_postal_code": extracted.ship_to.postal_code,
        "carrier_account": extracted.carrier_account.value,
    }
    for name in HEADER_FIELDS:
        want = truth.get(name)
        s.check(name, _same_text(got[name], want, loose=name in ("customer_name", "carrier_account")), got[name], want)

    want_lines = truth["lines"]
    for i in range(max(len(want_lines), len(extracted.lines))):
        want = want_lines[i] if i < len(want_lines) else None
        line = extracted.lines[i] if i < len(extracted.lines) else None
        for name in LINE_FIELDS:
            w = want[name] if want else None
            g = getattr(line, name).value if line else None
            if name == "customer_part":
                ok = normalize_part(g) == normalize_part(w)
            elif name in ("quantity", "unit_price"):
                ok = g is not None and w is not None and abs(float(g) - float(w)) < 0.005
            else:
                ok = _same_text(g, w)
            s.check(f"line {i + 1} {name}", ok, g, w)
    return s


def _same_text(got, want, loose: bool = False) -> bool:
    if got is None or want is None:
        return got is None and want is None
    a, b = " ".join(str(got).lower().split()), " ".join(str(want).lower().split())
    if loose:
        a, b = normalize_part(a), normalize_part(b)
        return a == b or a in b or b in a
    return a == b
