from generator.events import Topic
from platform_common.kafka_topics import TOPICS, TopicSpec, plan_topics

SPECS = (TopicSpec("a"), TopicSpec("b", partitions=6))


def test_every_generator_topic_is_declared() -> None:
    declared = {spec.name for spec in TOPICS}
    assert {str(topic) for topic in Topic} <= declared
    assert "dead_letter_events" in declared


def test_topic_names_are_unique() -> None:
    names = [spec.name for spec in TOPICS]
    assert len(names) == len(set(names))


def test_retention_is_converted_to_milliseconds() -> None:
    assert TopicSpec("x").config["retention.ms"] == "604800000"  # 7 days
    assert TopicSpec("x", retention_days=30).config["retention.ms"] == "2592000000"


def test_plan_creates_only_missing_topics() -> None:
    to_create, problems = plan_topics(SPECS, existing={"a": 3})
    assert [spec.name for spec in to_create] == ["b"]
    assert problems == []


def test_plan_is_a_no_op_when_everything_exists() -> None:
    assert plan_topics(SPECS, existing={"a": 3, "b": 6, "other": 1}) == ([], [])


def test_plan_reports_partition_mismatch_but_does_not_recreate() -> None:
    to_create, problems = plan_topics(SPECS, existing={"a": 1, "b": 6})
    assert to_create == []
    assert problems == ["a has 1 partitions, spec says 3"]
