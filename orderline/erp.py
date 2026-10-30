"""ERP reference data, loaded from CSV exports.

Orderline never writes to the ERP. It reads a nightly export of customers, ship-to addresses,
the item master with customer and legacy cross-references, units of measure and price lists,
and writes CSVs into the folder the existing import process already watches.
"""

from __future__ import annotations

import csv
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Customer:
    customer_id: str
    name: str
    aliases: list[str]
    email_domains: list[str]
    price_list: str


@dataclass
class ShipTo:
    ship_to_id: str
    customer_id: str
    name: str
    line1: str
    line2: str
    city: str
    state: str
    postal_code: str
    country: str

    def one_line(self) -> str:
        parts = [self.name, self.line1, self.line2, self.city, self.state, self.postal_code]
        return " ".join(p for p in parts if p)


@dataclass
class Item:
    item_number: str
    description: str
    base_uom: str
    active: bool


@dataclass
class UomRule:
    uom: str
    factor: float  # base units per one of this unit
    aliases: list[str]


@dataclass
class ErpData:
    customers: dict[str, Customer] = field(default_factory=dict)
    ship_tos: dict[str, list[ShipTo]] = field(default_factory=dict)  # by customer_id
    items: dict[str, Item] = field(default_factory=dict)
    xref: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)  # (customer|*, norm part) -> (item, kind)
    uoms: dict[str, list[UomRule]] = field(default_factory=dict)  # by item_number
    prices: dict[tuple[str, str, str], float] = field(default_factory=dict)  # (price_list, item, uom) -> price

    @classmethod
    def load(cls, folder: str | Path) -> "ErpData":
        folder = Path(folder)
        data = cls()
        for row in _rows(folder / "customers.csv"):
            data.customers[row["customer_id"]] = Customer(
                customer_id=row["customer_id"],
                name=row["name"],
                aliases=_split(row.get("aliases", "")),
                email_domains=[d.lower() for d in _split(row.get("email_domains", ""))],
                price_list=row.get("price_list") or "LIST",
            )
        for row in _rows(folder / "ship_to.csv"):
            data.ship_tos.setdefault(row["customer_id"], []).append(ShipTo(**{k: row.get(k, "") for k in ShipTo.__dataclass_fields__}))
        for row in _rows(folder / "items.csv"):
            data.items[row["item_number"]] = Item(
                item_number=row["item_number"],
                description=row["description"],
                base_uom=row["base_uom"],
                active=row.get("active", "Y").upper() in ("Y", "YES", "TRUE", "1"),
            )
        for row in _rows(folder / "item_xref.csv"):
            key = (row["customer_id"] or "*", normalize_part(row["customer_part"]))
            data.xref[key] = (row["item_number"], row.get("kind") or "customer")
        for row in _rows(folder / "uom.csv"):
            data.uoms.setdefault(row["item_number"], []).append(
                UomRule(uom=row["uom"], factor=float(row["factor"]), aliases=[a.lower() for a in _split(row.get("aliases", ""))])
            )
        for row in _rows(folder / "prices.csv"):
            data.prices[(row["price_list"], row["item_number"], row["uom"])] = float(row["unit_price"])
        return data


def normalize_part(value: str | None) -> str:
    if not value:
        return ""
    return "".join(ch for ch in value.upper() if ch.isalnum())


def _rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="") as handle:
        return [{k: (v or "").strip() for k, v in row.items()} for row in csv.DictReader(handle)]


def _split(value: str) -> list[str]:
    return [part.strip() for part in value.split("|") if part.strip()]
