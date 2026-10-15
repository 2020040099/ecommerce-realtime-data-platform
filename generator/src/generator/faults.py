"""Turn clean events into the messy stream a real ingestion pipeline receives."""

from __future__ import annotations

import json
import random
from collections.abc import Iterable
from dataclasses import dataclass, fields
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any

from generator.events import Event, Topic, format_timestamp

NETWORK_LATENCY_SECONDS = 0.2
REQUIRED_FIELDS = ("event_id", "event_type", "event_timestamp", "user_id", "session_id")


class FaultType(StrEnum):
    DUPLICATE = "duplicate"
    OUT_OF_ORDER = "out_of_order"
    LATE = "late"
    MISSING_FIELD = "missing_field"
    INVALID_VALUE = "invalid_value"
    MALFORMED_JSON = "malformed_json"


@dataclass(frozen=True, slots=True)
class FaultConfig:
    """Probability that any single event suffers each kind of fault."""

    duplicate: float = 0.02
    out_of_order: float = 0.05
    late: float = 0.03
    missing_field: float = 0.01
    invalid_value: float = 0.01
    malformed_json: float = 0.01

    def __post_init__(self) -> None:
        rates = [getattr(self, f.name) for f in fields(self)]
        if any(rate < 0 for rate in rates) or sum(rates) > 1:
            raise ValueError("fault rates must be >= 0 and sum to at most 1")

    @classmethod
    def none(cls) -> FaultConfig:
        """A config that injects no faults at all."""
        return cls(**{f.name: 0.0 for f in fields(cls)})

    def choices(self) -> tuple[list[FaultType | None], list[float]]:
        """Every possible outcome and its probability; None means 'stays clean'."""
        outcomes: list[FaultType | None] = [FaultType(f.name) for f in fields(self)]
        weights = [getattr(self, f.name) for f in fields(self)]
        return [*outcomes, None], [*weights, 1 - sum(weights)]


DEFAULT_FAULTS = FaultConfig()


@dataclass(frozen=True, slots=True)
class OutgoingRecord:
    """One message exactly as it leaves the client."""

    payload: str  # what goes on the wire: usually JSON, sometimes broken
    produced_at: datetime  # when the client actually sent it
    topic: Topic
    fault: FaultType | None  # ground truth for testing; never sent downstream


def apply_faults(
    events: Iterable[Event],
    rng: random.Random,
    config: FaultConfig = DEFAULT_FAULTS,
) -> list[OutgoingRecord]:
    """Serialize events, inject faults, and return records in the order they are sent."""
    outcomes, weights = config.choices()
    records: list[OutgoingRecord] = []
    for event in events:
        fault = rng.choices(outcomes, weights=weights, k=1)[0]
        records.extend(_emit(event, fault, rng))
    records.sort(key=lambda record: record.produced_at)
    return records


def _emit(event: Event, fault: FaultType | None, rng: random.Random) -> list[OutgoingRecord]:
    data = event.to_dict()
    latency = timedelta(seconds=rng.expovariate(1 / NETWORK_LATENCY_SECONDS))
    sent_at = event.event_timestamp + latency

    if fault is FaultType.OUT_OF_ORDER:
        sent_at += timedelta(seconds=rng.uniform(5, 120))
    elif fault is FaultType.LATE:
        sent_at += timedelta(minutes=rng.uniform(11, 60))
    elif fault is FaultType.MISSING_FIELD:
        del data[rng.choice(REQUIRED_FIELDS)]
    elif fault is FaultType.INVALID_VALUE:
        _corrupt_a_value(data, event, rng)

    data["produced_at"] = format_timestamp(sent_at)
    payload = json.dumps(data, ensure_ascii=False)

    if fault is FaultType.MALFORMED_JSON:
        payload = payload[: rng.randint(1, len(payload) - 1)]  # cut off mid-message

    if fault is FaultType.DUPLICATE:
        retry_at = sent_at + timedelta(seconds=rng.uniform(0.5, 5))
        return [
            OutgoingRecord(payload, sent_at, event.topic, None),
            OutgoingRecord(payload, retry_at, event.topic, FaultType.DUPLICATE),
        ]
    return [OutgoingRecord(payload, sent_at, event.topic, fault)]


def _corrupt_a_value(data: dict[str, Any], event: Event, rng: random.Random) -> None:
    options = ["unknown_event_type", "future_timestamp", "unparseable_timestamp"]
    if "price" in data:
        options.append("negative_price")
    if "quantity" in data:
        options.append("bad_quantity")

    corruption = rng.choice(options)
    if corruption == "unknown_event_type":
        data["event_type"] = "purchse"
    elif corruption == "future_timestamp":
        data["event_timestamp"] = format_timestamp(event.event_timestamp + timedelta(days=1))
    elif corruption == "unparseable_timestamp":
        data["event_timestamp"] = "not-a-timestamp"
    elif corruption == "negative_price":
        data["price"] = f"-{data['price']}"
    elif corruption == "bad_quantity":
        data["quantity"] = rng.choice([0, -1])
