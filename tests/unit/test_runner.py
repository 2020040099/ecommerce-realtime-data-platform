import random
from datetime import UTC, datetime, timedelta

import pytest
from generator.catalog import Catalog
from generator.faults import OutgoingRecord
from generator.runner import TICK_SECONDS, RunStats, run
from generator.sinks import Sink

START = datetime(2026, 1, 1, tzinfo=UTC)
CATALOG = Catalog()


class FakeClock:
    """Time that only moves when the code under test sleeps."""

    def __init__(self, stop_at: float | None = None) -> None:
        self.now = 0.0
        self.stop_at = stop_at

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds
        if self.stop_at is not None and self.now >= self.stop_at:
            raise KeyboardInterrupt  # simulate the user pressing Ctrl+C


class RecordingSink(Sink):
    """Keeps every record together with the (fake) time it was written."""

    def __init__(self, clock: FakeClock) -> None:
        self.clock = clock
        self.written: list[tuple[float, OutgoingRecord]] = []

    def write(self, record: OutgoingRecord) -> None:
        self.written.append((self.clock.now, record))


def run_fake(
    rate: float = 50, max_events: int | None = None, stop_at: float | None = None
) -> tuple[FakeClock, RecordingSink, RunStats]:
    clock = FakeClock(stop_at=stop_at)
    sink = RecordingSink(clock)
    stats = run(
        sink,
        random.Random(7),
        rate,
        catalog=CATALOG,
        max_events=max_events,
        start=START,
        clock=clock.time,
        sleep=clock.sleep,
    )
    return clock, sink, stats


def test_stops_after_max_events() -> None:
    _, sink, stats = run_fake(max_events=100)
    assert stats.emitted == len(sink.written) == 100


def test_never_emits_a_record_before_its_time() -> None:
    _, sink, _ = run_fake(max_events=500)
    for written_at, record in sink.written:
        assert record.produced_at <= START + timedelta(seconds=written_at)


def test_emits_records_in_produced_at_order() -> None:
    _, sink, _ = run_fake(max_events=500)
    times = [record.produced_at for _, record in sink.written]
    assert times == sorted(times)


def test_generation_keeps_up_with_the_target_rate() -> None:
    clock, _, stats = run_fake(rate=100, stop_at=60.0)
    target = 100 * clock.now
    # Behind by at most one tick; ahead by at most about one session.
    assert target - 100 * TICK_SECONDS - 1 <= stats.generated <= target + 150


def test_ctrl_c_stops_cleanly_and_accounts_for_every_record() -> None:
    _, sink, stats = run_fake(stop_at=30.0)
    assert stats.stopped_by_user
    assert stats.dropped > 0  # sessions still in progress at the moment we stopped
    assert stats.generated == stats.emitted + stats.dropped
    assert stats.emitted == len(sink.written)


def test_stats_count_every_emitted_record_by_topic_and_fault() -> None:
    _, _, stats = run_fake(max_events=2000)
    assert sum(stats.by_topic.values()) == stats.emitted
    assert sum(stats.by_fault.values()) == stats.emitted
    assert stats.by_fault["clean"] > stats.emitted * 0.8


@pytest.mark.parametrize("rate", [0, -5])
def test_rejects_non_positive_rate(rate: float) -> None:
    with pytest.raises(ValueError, match="rate must be positive"):
        run(RecordingSink(FakeClock()), random.Random(), rate)
