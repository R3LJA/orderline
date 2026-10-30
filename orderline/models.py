"""Data shapes that move through the pipeline.

Two layers on purpose:

* ``Extracted*`` models are the wire format the model must return. They forbid extra
  keys and carry no numeric constraints, so the same schema works with structured
  outputs and with replayed mock responses.
* ``PreparedOrder`` and friends are what the pipeline builds after matching against
  ERP data. They are never filled in by the model.
"""

from __future__ import annotations

from datetime import date
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class Wire(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TextField(Wire):
    value: str | None = Field(description="Exactly as printed, or null if absent or unreadable.")
    confidence: float = Field(description="0 to 1: how sure you are the value is read correctly.")
    page: int | None = Field(description="1-based page number in the original file.")


class NumberField(Wire):
    value: float | None = Field(description="Plain number without currency symbols or separators.")
    confidence: float
    page: int | None


class AddressField(Wire):
    name: str | None
    lines: list[str] = Field(description="Street lines, attention lines, suite numbers.")
    city: str | None
    state: str | None
    postal_code: str | None
    country: str | None
    confidence: float
    page: int | None


class ExtractedLine(Wire):
    line_number: int | None
    customer_part: TextField = Field(description="The part number as the customer wrote it.")
    description: TextField
    quantity: NumberField
    unit_of_measure: TextField = Field(description="As written, for example EA, BX, CS, case, box of 100.")
    unit_price: NumberField


class PageRole(StrEnum):
    order = "order"
    cover = "cover"
    terms = "terms"
    other = "other"


class PageNote(Wire):
    page: int
    role: PageRole
    rotation_seen: int = Field(description="0, 90, 180 or 270 if the page looked rotated to you.")


class ExtractedOrder(Wire):
    is_purchase_order: bool = Field(description="False for invoices, quotes, statements and anything else.")
    po_number: TextField
    customer_name: TextField
    order_date: TextField = Field(description="ISO 8601 date if you can tell it, else as printed.")
    requested_date: TextField = Field(description="Requested delivery or ship date, ISO 8601 if possible.")
    bill_to: AddressField
    ship_to: AddressField
    shipping_instructions: TextField
    carrier: TextField
    carrier_account: TextField = Field(description="Third-party carrier account number, if the PO lists one.")
    lines: list[ExtractedLine]
    pages: list[PageNote]
    notes: list[str] = Field(description="Anything a customer service rep should know, in one sentence each.")


# --------------------------------------------------------------------------- after matching


class Severity(StrEnum):
    blocker = "blocker"  # the order cannot be imported without a person fixing it
    check = "check"  # importable, but a person should confirm
    info = "info"


class FlagCode(StrEnum):
    missing_po_number = "missing_po_number"
    unclear_field = "unclear_field"
    unknown_customer = "unknown_customer"
    customer_uncertain = "customer_uncertain"
    unknown_ship_to = "unknown_ship_to"
    unknown_item = "unknown_item"
    item_fuzzy_match = "item_fuzzy_match"
    uom_mismatch = "uom_mismatch"
    price_mismatch = "price_mismatch"
    no_price_on_file = "no_price_on_file"
    possible_duplicate = "possible_duplicate"
    date_unclear = "date_unclear"
    orientation_uncertain = "orientation_uncertain"
    model_declined = "model_declined"
    no_lines = "no_lines"


class Flag(BaseModel):
    code: FlagCode
    severity: Severity
    message: str
    field: str | None = None
    line_number: int | None = None
    page: int | None = None
    expected: str | None = None
    found: str | None = None


class MatchedLine(BaseModel):
    line_number: int
    customer_part: str | None
    description: str | None
    quantity: float | None
    unit_of_measure: str | None  # canonical ERP code, for example BX
    unit_of_measure_as_written: str | None
    unit_price: float | None
    item_number: str | None
    match_method: str  # xref | legacy | item_number | normalized | fuzzy | none
    match_score: float
    list_price: float | None = None
    page: int | None = None


class MatchedShipTo(BaseModel):
    ship_to_id: str | None
    score: float
    as_written: str


class PreparedOrder(BaseModel):
    order_key: str
    source_message_id: str
    source_file: str
    sender: str | None
    customer_id: str | None
    customer_name: str | None
    customer_score: float
    po_number: str | None
    order_date: date | None
    requested_date: date | None
    ship_to: MatchedShipTo
    shipping_instructions: str | None
    carrier: str | None
    carrier_account: str | None
    lines: list[MatchedLine]
    flags: list[Flag]
    extraction_mode: str  # text | vision | mixed | mock
    page_count: int
    order_pages: list[int]
    content_hash: str
    status: str = "waiting_for_review"  # Orderline never releases an order

    @property
    def blockers(self) -> list[Flag]:
        return [f for f in self.flags if f.severity == Severity.blocker]

    @property
    def needs_attention(self) -> bool:
        return any(f.severity != Severity.info for f in self.flags)
