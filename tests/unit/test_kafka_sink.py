from datetime import UTC, datetime
from typing import Any

import pytest
from generator.events import Topic
from generator.faults import OutgoingRecord
from generator.kafka_sink import KafkaSink, extract_key


class FakeMessage:
    def __init__(self, topic: str) -> None:
        self._topic = topic

    def topic(self) -> str:
        return self._topic


class FakeProducer:
    """Records produce() calls and 'delivers' them on flush, like the real one."""

    def __init__(self, fail: bool = False, stuck: int = 0) -> None:
        self.sent: list[dict[str, Any]] = []
        self._pending: list[tuple[str, Any]] = []
        self.fail = fail
        self.stuck = stuck

    def produce(self, topic: str, value: str, key: str | None, on_delivery: Any) -> None:
        self.sent.append({"topic": topic, "value": value, "key": key})
        self._pending.append((topic, on_delivery))

    def poll(self, timeout: float) -> int:
        return 0

    def flush(self, timeout: float) -> int:
        for topic, callback in self._pending:
            callback("broker down" if self.fail else None, FakeMessage(topic))
        self._pending.clear()
        return self.stuck

    def __len__(self) -> int:  # like the real Producer: messages still queued
        return len(self._pending)


def make_record(payload: str, topic: Topic = Topic.USER_EVENTS) -> OutgoingRecord:
    return OutgoingRecord(
        payload=payload, produced_at=datetime(2026, 1, 1, tzinfo=UTC), topic=topic, fault=None
    )


@pytest.mark.parametrize(
    ("topic", "payload", "expected"),
    [
        ("user_events", '{"user_id": "u_1"}', "u_1"),
        ("purchase_events", '{"user_id": "u_2", "order_id": "o_9"}', "u_2"),
        ("user_events", '{"user_id": "u_1"', None),  # malformed JSON
        ("user_events", '{"event_id": "e1"}', None),  # key field missing
        ("user_events", '["not", "an", "object"]', None),
        ("user_events", '{"user_id": 42}', None),  # wrong type
        ("unknown_topic", '{"user_id": "u_1"}', None),
    ],
)
def test_extract_key(topic: str, payload: str, expected: str | None) -> None:
    assert extract_key(topic, payload) == expected


def test_write_sends_payload_to_the_records_topic_with_its_key() -> None:
    producer = FakeProducer()
    with KafkaSink("unused:9092", producer=producer) as sink:
        sink.write(make_record('{"user_id": "u_1"}'))

    assert producer.sent == [{"topic": "user_events", "value": '{"user_id": "u_1"}', "key": "u_1"}]
    assert sink.delivered == 1


def test_failed_deliveries_are_counted() -> None:
    producer = FakeProducer(fail=True)
    with KafkaSink("unused:9092", producer=producer) as sink:
        sink.write(make_record('{"user_id": "u_1"}'))
        sink.write(make_record('{"user_id": "u_2"}'))

    assert (sink.delivered, sink.failed) == (0, 2)


def test_messages_left_after_flush_are_logged_as_errors(caplog: pytest.LogCaptureFixture) -> None:
    with KafkaSink("unused:9092", producer=FakeProducer(stuck=3)):
        pass

    assert "kafka_undelivered" in caplog.messages
