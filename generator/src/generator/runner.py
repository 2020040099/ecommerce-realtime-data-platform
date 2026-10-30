"""Runner: turns the one-shot simulator into a continuous, real-time stream.

Each loop:
  1. top up - start new sessions until we've generated `rate * elapsed` records
  2. emit   - write every queued record whose produced_at has arrived
  3. rest   - sleep one tick
Records wait in a min-heap ordered by produced_at, so many sessions interleave
naturally and nothing is sent before its time.
"""

import heapq
import itertools
import random
import time
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta

from generator.catalog import Catalog
from generator.faults import DEFAULT_FAULTS, FaultConfig, OutgoingRecord, apply_faults
from generator.session import simulate_session
from generator.sinks import Sink

TICK_SECONDS = 0.05
NUM_USERS = 10_000


@dataclass
class RunStats:
    """What happened during a run. Every generated record is emitted or dropped."""

    generated: int = 0
    emitted: int = 0
    dropped: int = 0
    stopped_by_user: bool = False
    by_topic: Counter[str] = field(default_factory=Counter)
    by_fault: Counter[str] = field(default_factory=Counter)

    def count_emitted(self, record: OutgoingRecord) -> None:
        self.emitted += 1
        self.by_topic[str(record.topic)] += 1
        self.by_fault[str(record.fault) if record.fault else "clean"] += 1


def run(
    sink: Sink,
    rng: random.Random,
    rate: float,
    *,
    catalog: Catalog | None = None,
    faults: FaultConfig = DEFAULT_FAULTS,
    max_events: int | None = None,
    start: datetime | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> RunStats:
    """Generate records at `rate` per second and write them to `sink` in real time.

    Stops after `max_events` records, or on Ctrl+C (KeyboardInterrupt).
    Records still queued at that point are dropped: they belong to the future.
    """
    if rate <= 0:
        raise ValueError(f"rate must be positive, got {rate}")
    if catalog is None:  # not `catalog or Catalog()`: Catalog has __len__
        catalog = Catalog()
    if start is None:
        start = datetime.now(UTC)

    queue: list[tuple[datetime, int, OutgoingRecord]] = []
    tiebreak = itertools.count()
    stats = RunStats()
    t0 = clock()

    def limit_reached() -> bool:
        return max_events is not None and stats.emitted >= max_events

    try:
        while not limit_reached():
            elapsed = clock() - t0
            now = start + timedelta(seconds=elapsed)

            # 1. Top up: start sessions until we are no longer behind schedule.
            while stats.generated < rate * elapsed:
                user_id = f"u_{rng.randrange(NUM_USERS):05d}"
                events = simulate_session(catalog, rng, now, user_id)
                for record in apply_faults(events, rng, faults):
                    heapq.heappush(queue, (record.produced_at, next(tiebreak), record))
                    stats.generated += 1

            # 2. Emit: everything whose time has come, earliest first.
            while queue and queue[0][0] <= now and not limit_reached():
                _, _, record = heapq.heappop(queue)
                sink.write(record)
                stats.count_emitted(record)

            # 3. Rest.
            sleep(TICK_SECONDS)
    except KeyboardInterrupt:
        stats.stopped_by_user = True

    stats.dropped = len(queue)
    return stats
