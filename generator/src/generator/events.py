"""Event model: the vocabulary of event types and the shape of a single event."""

from __future__ import annotations

import json
import uuid
from collections.abc import Sequence
from dataclasses import dataclass, field, fields
from datetime import UTC, datetime
from decimal import Decimal
from enum import StrEnum
from typing import Any

SCHEMA_VERSION = "1.1"
CURRENCY = "USD"


class EventType(StrEnum):
    USER_VIEW = "user_view"
    PRODUCT_CLICK = "product_click"
    SEARCH = "search"
    ADD_TO_CART = "add_to_cart"
    REMOVE_FROM_CART = "remove_from_cart"
    CHECKOUT = "checkout"
    PURCHASE = "purchase"
    PAYMENT_SUCCESS = "payment_success"
    PAYMENT_FAILED = "payment_failed"
    INVENTORY_UPDATE = "inventory_update"


class Topic(StrEnum):
    USER_EVENTS = "user_events"
    PURCHASE_EVENTS = "purchase_events"
    INVENTORY_EVENTS = "inventory_events"


TOPIC_BY_EVENT_TYPE: dict[EventType, Topic] = {
    EventType.USER_VIEW: Topic.USER_EVENTS,
    EventType.PRODUCT_CLICK: Topic.USER_EVENTS,
    EventType.SEARCH: Topic.USER_EVENTS,
    EventType.ADD_TO_CART: Topic.USER_EVENTS,
    EventType.REMOVE_FROM_CART: Topic.USER_EVENTS,
    EventType.CHECKOUT: Topic.PURCHASE_EVENTS,
    EventType.PURCHASE: Topic.PURCHASE_EVENTS,
    EventType.PAYMENT_SUCCESS: Topic.PURCHASE_EVENTS,
    EventType.PAYMENT_FAILED: Topic.PURCHASE_EVENTS,
    EventType.INVENTORY_UPDATE: Topic.INVENTORY_EVENTS,
}


def topic_for(event_type: EventType) -> Topic:
    """Return the Kafka topic an event of this type is published to."""
    return TOPIC_BY_EVENT_TYPE[event_type]


@dataclass(frozen=True, slots=True)
class OrderItem:
    """One line of an order: a product, its unit price at purchase time, and a quantity."""

    product_id: str
    category: str
    unit_price: Decimal
    quantity: int

    @property
    def line_total(self) -> Decimal:
        return self.unit_price * self.quantity

    def to_dict(self) -> dict[str, Any]:
        return {f.name: _to_json_value(getattr(self, f.name)) for f in fields(self)}


def order_total(items: Sequence[OrderItem]) -> Decimal:
    """Sum of unit_price x quantity across all lines."""
    return sum((item.line_total for item in items), Decimal("0"))


@dataclass(frozen=True, slots=True)
class Event:
    """One e-commerce event, exactly as it will be published downstream.

    Fields that do not apply to an event type stay None and are omitted
    from the serialized output.
    """

    # --- envelope: present on every event ---
    event_type: EventType
    event_timestamp: datetime
    user_id: str
    session_id: str
    device_type: str
    country: str
    source: str

    # --- user-behaviour fields: present only on some event types ---
    product_id: str | None = None
    category: str | None = None
    price: Decimal | None = None
    quantity: int | None = None
    search_query: str | None = None

    # --- order & payment fields (added in schema 1.1) ---
    order_id: str | None = None
    items: tuple[OrderItem, ...] | None = None
    order_amount: Decimal | None = None
    currency: str | None = None
    payment_id: str | None = None
    payment_method: str | None = None
    failure_reason: str | None = None

    # --- filled in automatically ---
    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    schema_version: str = SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.event_timestamp.tzinfo is None:
            raise ValueError("event_timestamp must be timezone-aware (use UTC)")
        if self.items is not None and self.order_amount is not None:
            expected = order_total(self.items)
            if self.order_amount != expected:
                raise ValueError(f"order_amount {self.order_amount} != sum of items {expected}")

    @property
    def topic(self) -> Topic:
        return topic_for(self.event_type)

    def to_dict(self) -> dict[str, Any]:
        """Convert to a JSON-ready dict, dropping fields that are None."""
        result: dict[str, Any] = {}
        for f in fields(self):
            value = getattr(self, f.name)
            if value is not None:
                result[f.name] = _to_json_value(value)
        return result

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False)


def format_timestamp(ts: datetime) -> str:
    """ISO-8601 in UTC with milliseconds, e.g. 2026-10-06T08:15:02.341Z."""
    return ts.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _to_json_value(value: Any) -> Any:
    if isinstance(value, datetime):
        return format_timestamp(value)
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, OrderItem):
        return value.to_dict()
    if isinstance(value, tuple):
        return [_to_json_value(v) for v in value]
    return value
