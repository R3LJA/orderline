"""Write one CSV per order in the column spec the ERP import expects, plus a JSON sidecar.

The CSV is the only thing the ERP import sees. The sidecar keeps everything a rep or an
auditor needs: every flag, the match method and score for every line, the source file and
pages. Orders with blockers are still written, with ``REVIEW_STATUS=blocked`` on every row,
so nothing is lost and the review step decides.
"""

from __future__ import annotations

import csv
import io
import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

import yaml

from .models import PreparedOrder


@dataclass
class Column:
    name: str
    source: str
    format: str | None = None


@dataclass
class CsvSpec:
    filename: str
    delimiter: str
    header: bool
    date_format: str
    columns: list[Column]

    @classmethod
    def load(cls, path: str | Path) -> "CsvSpec":
        raw = yaml.safe_load(Path(path).read_text())
        return cls(
            filename=raw.get("filename", "{order_key}.csv"),
            delimiter=raw.get("delimiter", ","),
            header=bool(raw.get("header", True)),
            date_format=raw.get("date_format", "%Y-%m-%d"),
            columns=[Column(**c) for c in raw["columns"]],
        )


def review_status(order: PreparedOrder) -> str:
    if order.blockers:
        return "blocked"
    return "check" if order.needs_attention else "clean"


def render_csv(order: PreparedOrder, spec: CsvSpec) -> str:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=spec.delimiter, lineterminator="\n")
    if spec.header:
        writer.writerow([c.name for c in spec.columns])
    rows = order.lines or [None]
    for line in rows:
        writer.writerow([_cell(order, line, column, spec) for column in spec.columns])
    return buf.getvalue()


def write_order(order: PreparedOrder, spec: CsvSpec, out_dir: str | Path) -> tuple[Path, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    name = spec.filename.format(
        customer_id=_safe(order.customer_id or "UNKNOWN"),
        po_number=_safe(order.po_number or "NOPO"),
        order_key=order.order_key,
    )
    csv_path = out / name
    csv_path.write_text(render_csv(order, spec))
    sidecar = csv_path.with_suffix(".json")
    payload = order.model_dump(mode="json")
    payload["review_status"] = review_status(order)
    sidecar.write_text(json.dumps(payload, indent=2))
    return csv_path, sidecar


def _cell(order: PreparedOrder, line, column: Column, spec: CsvSpec) -> str:
    scope, _, path = column.source.partition(".")
    if scope == "order":
        if path == "review_status":
            value: Any = review_status(order)
        elif path == "flag_codes":
            value = "|".join(sorted({f.code.value for f in order.flags}))
        else:
            value = _lookup(order, path)
    elif scope == "line":
        value = _lookup(line, path) if line is not None else None
    else:
        raise ValueError(f"unknown column source {column.source!r}")
    if value is None:
        return ""
    if isinstance(value, date):
        return value.strftime(spec.date_format)
    if column.format:
        return column.format.format(value)
    return str(value)


def _lookup(obj: Any, path: str) -> Any:
    for part in path.split("."):
        if obj is None:
            return None
        obj = getattr(obj, part, None)
    return obj


def _safe(value: str) -> str:
    return re.sub(r"[^A-Za-z0-9_-]+", "-", value).strip("-") or "X"
