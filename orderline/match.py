"""Match what the customer wrote against ERP reference data, with explicit scores.

Every match records how it was made (cross-reference, legacy number, normalized, fuzzy) and a
0 to 100 score, so a rep can see why Orderline picked an item and the review report can show it.
Fuzzy matches are never silent: anything below an exact cross-reference is flagged for a check.
"""

from __future__ import annotations

from dataclasses import dataclass

from rapidfuzz import fuzz

from .erp import ErpData, ShipTo, UomRule, normalize_part
from .models import AddressField


@dataclass
class Settings:
    confidence_threshold: float = 0.80  # model confidence below this becomes an "unclear field" flag
    customer_accept: float = 90.0
    customer_check: float = 75.0
    ship_to_accept: float = 85.0
    item_fuzzy_min: float = 90.0
    price_tolerance_pct: float = 0.5  # differences above this are flagged
    price_tolerance_abs: float = 0.01


@dataclass
class CustomerMatch:
    customer_id: str | None
    name: str | None
    score: float
    method: str


@dataclass
class ShipToMatch:
    ship_to: ShipTo | None
    score: float


@dataclass
class ItemMatch:
    item_number: str | None
    method: str  # xref | legacy | item_number | normalized | fuzzy | none
    score: float
    candidate: str | None = None  # best fuzzy candidate, shown to the rep even when not accepted


@dataclass
class UomMatch:
    uom: str | None
    factor: float | None


def match_customer(erp: ErpData, name: str | None, sender_domain: str) -> CustomerMatch:
    best: CustomerMatch = CustomerMatch(None, None, 0.0, "none")
    for customer in erp.customers.values():
        domain_hit = bool(sender_domain) and sender_domain in customer.email_domains
        name_score = 0.0
        if name:
            candidates = [customer.name, *customer.aliases]
            name_score = max(fuzz.token_set_ratio(name.lower(), c.lower()) for c in candidates)
        if domain_hit and name_score >= 60:
            score, method = 100.0, "domain+name"
        elif domain_hit:
            score, method = 92.0, "domain"
        else:
            score, method = float(name_score), "name"
        if score > best.score:
            best = CustomerMatch(customer.customer_id, customer.name, score, method)
    return best


def match_ship_to(erp: ErpData, customer_id: str | None, address: AddressField) -> ShipToMatch:
    if not customer_id:
        return ShipToMatch(None, 0.0)
    written = " ".join(
        p for p in [address.name, *address.lines, address.city, address.state, address.postal_code] if p
    )
    if not written.strip():
        return ShipToMatch(None, 0.0)
    best = ShipToMatch(None, 0.0)
    for ship_to in erp.ship_tos.get(customer_id, []):
        score = fuzz.token_set_ratio(written.lower(), ship_to.one_line().lower())
        if address.postal_code and ship_to.postal_code:
            same_zip = address.postal_code.replace(" ", "")[:5] == ship_to.postal_code.replace(" ", "")[:5]
            score = min(100.0, score + 10) if same_zip else score - 20
        if score > best.score:
            best = ShipToMatch(ship_to, float(score))
    return best


def match_item(erp: ErpData, customer_id: str | None, part: str | None, description: str | None, settings: Settings) -> ItemMatch:
    norm = normalize_part(part)
    if norm:
        if customer_id and (customer_id, norm) in erp.xref:
            item, kind = erp.xref[(customer_id, norm)]
            return ItemMatch(item, "xref" if kind == "customer" else kind, 100.0)
        if ("*", norm) in erp.xref:
            item, kind = erp.xref[("*", norm)]
            return ItemMatch(item, kind, 100.0)
        if part and part.strip().upper() in erp.items:
            return ItemMatch(part.strip().upper(), "item_number", 100.0)
        for number in erp.items:
            if normalize_part(number) == norm:
                return ItemMatch(number, "normalized", 98.0)

    # fuzzy: part numbers first (typos, a dropped dash), then descriptions only as a hint
    best_item, best_score = None, 0.0
    if norm:
        keys = list(erp.items) + [k[1] for k in erp.xref if k[0] in ("*", customer_id)]
        for key in keys:
            score = fuzz.ratio(norm, normalize_part(key))
            if score > best_score:
                target = key if key in erp.items else _xref_target(erp, customer_id, key)
                best_item, best_score = target, float(score)
    if best_item and best_score >= settings.item_fuzzy_min:
        return ItemMatch(best_item, "fuzzy", best_score, candidate=best_item)

    hint = None
    if description:
        scored = [
            (fuzz.token_set_ratio(description.lower(), item.description.lower()), item.item_number)
            for item in erp.items.values()
        ]
        top_score, top_item = max(scored) if scored else (0, None)
        if top_score >= 70:
            hint = top_item
    return ItemMatch(None, "none", best_score, candidate=hint or best_item)


def match_uom(erp: ErpData, item_number: str | None, written: str | None) -> UomMatch:
    if not item_number or not written:
        return UomMatch(None, None)
    rules: list[UomRule] = erp.uoms.get(item_number, [])
    token = written.strip().lower().rstrip(".")
    for rule in rules:
        if token == rule.uom.lower() or token in rule.aliases:
            return UomMatch(rule.uom, rule.factor)
    return UomMatch(None, None)


def list_price(erp: ErpData, price_list: str, item_number: str | None, uom: str | None) -> float | None:
    if not item_number or not uom:
        return None
    for key in ((price_list, item_number, uom), ("LIST", item_number, uom)):
        if key in erp.prices:
            return erp.prices[key]
    return None


def price_differs(written: float, expected: float, settings: Settings) -> bool:
    diff = abs(written - expected)
    return diff > settings.price_tolerance_abs and diff > expected * settings.price_tolerance_pct / 100


def _xref_target(erp: ErpData, customer_id: str | None, norm_key: str) -> str | None:
    for scope in (customer_id, "*"):
        if scope and (scope, norm_key) in erp.xref:
            return erp.xref[(scope, norm_key)][0]
    return None
