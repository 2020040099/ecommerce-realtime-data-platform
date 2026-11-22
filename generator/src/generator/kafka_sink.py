"""KafkaSink: send records to Kafka, keyed so each user's events stay in order."""

import json
import logging
from typing import Any

from confluent_kafka import KafkaError, Message, Producer

from generator.faults import OutgoingRecord
from generator.sinks import Sink

logger = logging.getLogger(__name__)

# Same key -> same partition -> ordered. Purchase events are keyed by user too,
# so checkout -> purchase -> payment for one user stays in order.
KEY_FIELD_BY_TOPIC = {
    "user_events": "user_id",
    "purchase_events": "user_id",
    "inventory_events": "product_id",
}

FLUSH_TIMEOUT_SECONDS = 10.0


def extract_key(topic: str, payload: str) -> str | None:
    """The partition key, or None if the payload is too broken to read it from."""
    field = KEY_FIELD_BY_TOPIC.get(topic)
    if field is None:
        return None
    try:
        data = json.loads(payload)
    except json.JSONDecodeError:
        return None
    value = data.get(field) if isinstance(data, dict) else None
    return value if isinstance(value, str) else None


def producer_config(bootstrap_servers: str) -> dict[str, Any]:
    return {
        "bootstrap.servers": bootstrap_servers,
        "client.id": "generator",
        "acks": "all",
        "enable.idempotence": True,  # retries never duplicate or reorder messages
        "linger.ms": 20,  # wait up to 20 ms to batch messages together
        "compression.type": "lz4",
    }


class KafkaSink(Sink):
    """Writes each record's payload to the record's topic."""

    def __init__(self, bootstrap_servers: str, producer: Producer | None = None) -> None:
        # `is None`, not `or`: Producer defines __len__, so an empty one is falsy.
        if producer is None:
            producer = Producer(producer_config(bootstrap_servers))
        self._producer = producer
        self.delivered = 0
        self.failed = 0

    def write(self, record: OutgoingRecord) -> None:
        topic = str(record.topic)
        key = extract_key(topic, record.payload)
        while True:
            try:
                self._producer.produce(
                    topic, value=record.payload, key=key, on_delivery=self._on_delivery
                )
                break
            except BufferError:
                # Local queue is full: let the background thread send some, then retry.
                self._producer.poll(1.0)
        self._producer.poll(0)  # serve delivery callbacks without blocking

    def close(self) -> None:
        remaining = self._producer.flush(FLUSH_TIMEOUT_SECONDS)
        if remaining:
            logger.error("kafka_undelivered", extra={"undelivered": remaining})
        logger.info("kafka_sink_closed", extra={"delivered": self.delivered, "failed": self.failed})

    def _on_delivery(self, err: KafkaError | None, msg: Message) -> None:
        if err is None:
            self.delivered += 1
        else:
            self.failed += 1
            logger.error("kafka_delivery_failed", extra={"topic": msg.topic(), "error": str(err)})
