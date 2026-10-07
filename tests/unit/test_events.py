"""Unit tests for generator.events."""

import json
import uuid
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
from typing import Any

import pytest
from generator.events import TOPIC_BY_EVENT_TYPE, Event, EventType, Topic, topic_for

pytestmark = pytest.mark.unit


def make_event(**overrides: Any) -> Event:
    """A valid baseline event; each test overrides only what it cares about."""
    attrs: dict[str, Any] = {
        "event_type": EventType.USER_VIEW,
        "event_timestamp": datetime(2026, 10, 6, 8, 15, 2, 341000, tzinfo=UTC),
        "user_id": "u_000123",
        "session_id": "s_abc",
        "device_type": "ios",
        "country": "AU",
        "source": "organic",
    }
    attrs.update(overrides)
    return Event(**attrs)


# ------------------------------------------------------------------
# Event types & topics
# ------------------------------------------------------------------
def test_every_event_type_has_a_topic() -> None:
    assert set(TOPIC_BY_EVENT_TYPE) == set(EventType)


def test_purchase_goes_to_purchase_topic() -> None:
    assert topic_for(EventType.PURCHASE) is Topic.PURCHASE_EVENTS


def test_event_type_equals_its_plain_string() -> None:
    assert EventType.ADD_TO_CART == "add_to_cart"


def test_unknown_event_type_is_rejected() -> None:
    with pytest.raises(ValueError):
        EventType("purchse")


# ------------------------------------------------------------------
# Event
# ------------------------------------------------------------------
def test_timestamp_serialized_as_utc_iso8601() -> None:
    assert make_event().to_dict()["event_timestamp"] == "2026-10-06T08:15:02.341Z"


def test_non_utc_timestamp_is_converted_to_utc() -> None:
    shanghai = timezone(timedelta(hours=8))
    local = datetime(2026, 10, 6, 16, 15, 2, 341000, tzinfo=shanghai)
    assert make_event(event_timestamp=local).to_dict()["event_timestamp"] == (
        "2026-10-06T08:15:02.341Z"
    )


def test_naive_timestamp_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        make_event(event_timestamp=datetime(2026, 10, 6, 8, 15))


def test_none_fields_are_omitted() -> None:
    data = make_event().to_dict()
    assert "price" not in data
    assert "product_id" not in data


def test_price_is_serialized_as_exact_string() -> None:
    assert make_event(price=Decimal("19.99")).to_dict()["price"] == "19.99"


def test_each_event_gets_a_unique_uuid() -> None:
    a, b = make_event(), make_event()
    assert a.event_id != b.event_id
    uuid.UUID(a.event_id)  # raises ValueError if not a valid UUID


def test_topic_is_derived_from_event_type() -> None:
    assert make_event(event_type=EventType.PURCHASE).topic is Topic.PURCHASE_EVENTS


def test_to_json_round_trips_to_the_same_dict() -> None:
    event = make_event(price=Decimal("19.99"), product_id="p_0042")
    assert json.loads(event.to_json()) == event.to_dict()


def test_event_is_immutable() -> None:
    event = make_event()
    with pytest.raises(FrozenInstanceError):
        event.price = Decimal("1.00")
