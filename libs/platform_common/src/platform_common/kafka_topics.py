"""Kafka topics as code: one declarative list, created idempotently.

Run `make topics` after `make up`. Running it again is safe: existing topics
are left alone, and differences are reported as warnings - never auto-"fixed".
"""

import logging
import os
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from confluent_kafka.admin import AdminClient, NewTopic

from platform_common.log import configure_logging

logger = logging.getLogger(__name__)

DAY_MS = 24 * 60 * 60 * 1000
DEFAULT_BOOTSTRAP_SERVERS = "localhost:9092"


@dataclass(frozen=True, slots=True)
class TopicSpec:
    name: str
    partitions: int = 3
    retention_days: int = 7

    @property
    def config(self) -> dict[str, str]:
        return {"retention.ms": str(self.retention_days * DAY_MS), "cleanup.policy": "delete"}


TOPICS: tuple[TopicSpec, ...] = (
    TopicSpec("user_events"),
    TopicSpec("purchase_events"),
    TopicSpec("inventory_events"),
    TopicSpec("dead_letter_events", retention_days=30),  # time to investigate bad data
)


def plan_topics(
    specs: Iterable[TopicSpec], existing: Mapping[str, int]
) -> tuple[list[TopicSpec], list[str]]:
    """Decide what to do. `existing` maps topic name -> partition count. Pure: no Kafka."""
    to_create: list[TopicSpec] = []
    problems: list[str] = []
    for spec in specs:
        actual = existing.get(spec.name)
        if actual is None:
            to_create.append(spec)
        elif actual != spec.partitions:
            # Never change partitions automatically: it remaps keys and breaks ordering.
            problems.append(f"{spec.name} has {actual} partitions, spec says {spec.partitions}")
    return to_create, problems


def ensure_topics(
    admin: AdminClient, specs: Iterable[TopicSpec] = TOPICS, replication_factor: int = 1
) -> list[str]:
    """Create the topics that are missing. Returns the names that were created."""
    metadata = admin.list_topics(timeout=10)
    existing = {name: len(topic.partitions) for name, topic in metadata.topics.items()}

    to_create, problems = plan_topics(specs, existing)
    for problem in problems:
        logger.warning("topic_mismatch", extra={"detail": problem})
    if not to_create:
        return []

    new_topics = [
        NewTopic(
            spec.name,
            num_partitions=spec.partitions,
            replication_factor=replication_factor,
            config=spec.config,
        )
        for spec in to_create
    ]
    for name, future in admin.create_topics(new_topics).items():
        future.result()  # raises if Kafka refused to create it
        logger.info("topic_created", extra={"topic": name})
    return [spec.name for spec in to_create]


def main() -> int:
    configure_logging(component="kafka-topics")
    bootstrap = os.getenv("KAFKA_BOOTSTRAP_SERVERS", DEFAULT_BOOTSTRAP_SERVERS)
    replication_factor = int(os.getenv("KAFKA_REPLICATION_FACTOR", "1"))

    admin = AdminClient({"bootstrap.servers": bootstrap})
    created = ensure_topics(admin, TOPICS, replication_factor)
    logger.info(
        "topics_ready",
        extra={"bootstrap_servers": bootstrap, "created_topics": created, "declared": len(TOPICS)},
    )
    return 0
