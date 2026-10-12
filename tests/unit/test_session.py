"""Unit tests for generator.session."""

import random
from datetime import UTC, datetime
from itertools import pairwise

import pytest
from generator.catalog import Catalog
from generator.events import Event, EventType
from generator.session import MAX_EVENTS_PER_SESSION, TRANSITIONS, simulate_session

pytestmark = pytest.mark.unit

START_TIME = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
CATALOG = Catalog(size=200)


def run_session(seed: int) -> list[Event]:
    return simulate_session(CATALOG, random.Random(seed), START_TIME, "u_000001")


def many_sessions(n: int = 2000) -> list[list[Event]]:
    rng = random.Random(0)
    return [simulate_session(CATALOG, rng, START_TIME, f"u_{i}") for i in range(n)]


def types(session: list[Event]) -> list[EventType]:
    return [e.event_type for e in session]


# ------------------------------------------------------------------
# The transition table itself
# ------------------------------------------------------------------
def test_every_row_of_probabilities_sums_to_one() -> None:
    for state, options in TRANSITIONS.items():
        assert sum(p for _, p in options) == pytest.approx(1.0), state


# ------------------------------------------------------------------
# A single session
# ------------------------------------------------------------------
def test_all_events_share_the_same_session_context() -> None:
    session = run_session(seed=1)
    assert (
        len({(e.user_id, e.session_id, e.device_type, e.country, e.source) for e in session}) == 1
    )


def test_timestamps_never_go_backwards() -> None:
    session = run_session(seed=1)
    stamps = [e.event_timestamp for e in session]
    assert stamps == sorted(stamps)
    assert stamps[0] > START_TIME


def test_same_seed_produces_the_same_session() -> None:
    def fingerprint(s: list[Event]) -> list[tuple]:
        return [(e.event_type, e.product_id, e.event_timestamp, e.session_id) for e in s]

    assert fingerprint(run_session(seed=42)) == fingerprint(run_session(seed=42))


# ------------------------------------------------------------------
# Business rules, checked across many sessions
# ------------------------------------------------------------------
def test_session_starts_with_view_or_search() -> None:
    for session in many_sessions():
        if session:
            assert session[0].event_type in (EventType.USER_VIEW, EventType.SEARCH)


def test_click_is_always_on_the_product_just_viewed() -> None:
    for session in many_sessions():
        for previous, event in pairwise(session):
            if event.event_type is EventType.PRODUCT_CLICK:
                assert previous.event_type is EventType.USER_VIEW
                assert event.product_id == previous.product_id


def test_checkout_only_happens_with_items_in_the_cart() -> None:
    for session in many_sessions():
        for event in session:
            if event.event_type is EventType.CHECKOUT:
                assert event.quantity is not None and event.quantity > 0


def test_sessions_respect_the_length_limit() -> None:
    assert all(len(s) <= MAX_EVENTS_PER_SESSION for s in many_sessions())


def test_funnel_narrows_at_every_step() -> None:
    sessions = many_sessions()

    def reached(step: EventType) -> int:
        return sum(step in types(s) for s in sessions)

    viewed = reached(EventType.USER_VIEW)
    carted = reached(EventType.ADD_TO_CART)
    checked_out = reached(EventType.CHECKOUT)
    assert viewed > carted > checked_out > 0
