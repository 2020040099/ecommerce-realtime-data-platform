"""Unit tests for generator.faults."""

import json
import random
from collections import Counter
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

import pytest
from generator.catalog import Catalog
from generator.events import EventType
from generator.faults import (
    REQUIRED_FIELDS,
    FaultConfig,
    FaultType,
    OutgoingRecord,
    apply_faults,
)
from generator.session import simulate_session

pytestmark = pytest.mark.unit

START_TIME = datetime(2026, 10, 13, 9, 0, tzinfo=UTC)
WATERMARK = timedelta(minutes=10)
KNOWN_EVENT_TYPES = {e.value for e in EventType}


def _clean_events() -> list:
    catalog = Catalog(size=200)
    rng = random.Random(0)
    return [e for i in range(5000) for e in simulate_session(catalog, rng, START_TIME, f"u_{i}")]


CLEAN_EVENTS = _clean_events()
RECORDS = apply_faults(CLEAN_EVENTS, random.Random(1))


def with_fault(fault: FaultType) -> list[OutgoingRecord]:
    return [r for r in RECORDS if r.fault is fault]


def event_time(record: OutgoingRecord) -> datetime:
    return datetime.fromisoformat(json.loads(record.payload)["event_timestamp"])


def breaks_a_business_rule(data: dict[str, Any]) -> bool:
    if data["event_type"] not in KNOWN_EVENT_TYPES:
        return True
    if Decimal(data.get("price", "0")) < 0:
        return True
    if data.get("quantity", 1) <= 0:
        return True
    try:
        happened_at = datetime.fromisoformat(data["event_timestamp"])
    except ValueError:
        return True
    return happened_at > datetime.fromisoformat(data["produced_at"])


# ------------------------------------------------------------------
# Overall stream
# ------------------------------------------------------------------
def test_no_faults_means_one_clean_record_per_event() -> None:
    events = CLEAN_EVENTS[:500]
    records = apply_faults(events, random.Random(1), FaultConfig.none())

    assert len(records) == len(events)
    assert all(r.fault is None for r in records)
    expected = {e.event_id: e.to_dict() for e in events}
    for record in records:
        data = json.loads(record.payload)
        data.pop("produced_at")
        assert data == expected[data["event_id"]]


def test_records_are_in_send_order() -> None:
    times = [r.produced_at for r in RECORDS]
    assert times == sorted(times)


@pytest.mark.parametrize("fault", list(FaultType))
def test_each_fault_occurs_at_roughly_its_configured_rate(fault: FaultType) -> None:
    observed = len(with_fault(fault)) / len(CLEAN_EVENTS)
    configured = getattr(FaultConfig(), fault.value)
    assert observed == pytest.approx(configured, rel=0.3)


def test_same_seed_produces_the_same_stream() -> None:
    a = apply_faults(CLEAN_EVENTS[:1000], random.Random(9))
    b = apply_faults(CLEAN_EVENTS[:1000], random.Random(9))
    assert [r.payload for r in a] == [r.payload for r in b]


def test_invalid_fault_config_is_rejected() -> None:
    with pytest.raises(ValueError):
        FaultConfig(duplicate=0.6, late=0.6)
    with pytest.raises(ValueError):
        FaultConfig(late=-0.1)


# ------------------------------------------------------------------
# Each fault type behaves as described
# ------------------------------------------------------------------
def test_duplicates_are_byte_identical_copies() -> None:
    payload_counts = Counter(r.payload for r in RECORDS)
    for record in with_fault(FaultType.DUPLICATE):
        assert payload_counts[record.payload] == 2


def test_out_of_order_records_arrive_within_the_watermark() -> None:
    for record in with_fault(FaultType.OUT_OF_ORDER):
        assert timedelta(seconds=5) < record.produced_at - event_time(record) < WATERMARK


def test_late_records_arrive_after_the_watermark() -> None:
    for record in with_fault(FaultType.LATE):
        assert record.produced_at - event_time(record) > WATERMARK


def test_missing_field_records_lack_a_required_field() -> None:
    for record in with_fault(FaultType.MISSING_FIELD):
        assert not set(REQUIRED_FIELDS) <= json.loads(record.payload).keys()


def test_malformed_records_are_not_valid_json() -> None:
    for record in with_fault(FaultType.MALFORMED_JSON):
        with pytest.raises(json.JSONDecodeError):
            json.loads(record.payload)


def test_invalid_value_records_break_a_business_rule() -> None:
    for record in with_fault(FaultType.INVALID_VALUE):
        assert breaks_a_business_rule(json.loads(record.payload))


def test_clean_records_break_no_business_rule() -> None:
    for record in RECORDS:
        if record.fault is None:
            assert not breaks_a_business_rule(json.loads(record.payload))
