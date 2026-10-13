"""Unit tests for generator.session."""

import random
from datetime import UTC, datetime
from decimal import Decimal
from itertools import pairwise

import pytest
from generator.catalog import Catalog, Product
from generator.events import Event, EventType
from generator.session import (
    END,
    MAX_EVENTS_PER_SESSION,
    START,
    TRANSITIONS,
    cart_to_items,
    simulate_session,
)

pytestmark = pytest.mark.unit

START_TIME = datetime(2026, 10, 7, 9, 0, tzinfo=UTC)
CATALOG = Catalog(size=200)


def run_session(seed: int) -> list[Event]:
    return simulate_session(CATALOG, random.Random(seed), START_TIME, "u_000001")


def many_sessions(n: int = 5000) -> list[list[Event]]:
    rng = random.Random(0)
    return [simulate_session(CATALOG, rng, START_TIME, f"u_{i}") for i in range(n)]


SESSIONS = many_sessions()  # built once, shared by the business-rule tests below


def types(session: list[Event]) -> list[EventType]:
    return [e.event_type for e in session]


def all_events(event_type: EventType) -> list[Event]:
    return [e for s in SESSIONS for e in s if e.event_type is event_type]


# ------------------------------------------------------------------
# The transition table itself
# ------------------------------------------------------------------
def test_every_row_of_probabilities_sums_to_one() -> None:
    for state, options in TRANSITIONS.items():
        assert sum(p for _, p in options) == pytest.approx(1.0), state


def test_every_session_event_type_has_a_row() -> None:
    reachable = {s for options in TRANSITIONS.values() for s, _ in options} - {END}
    assert reachable <= set(TRANSITIONS) - {START}
    assert EventType.INVENTORY_UPDATE not in TRANSITIONS  # produced elsewhere, not by users


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
        return [(e.event_type, e.product_id, e.event_timestamp, e.order_id) for e in s]

    assert fingerprint(run_session(seed=42)) == fingerprint(run_session(seed=42))


# ------------------------------------------------------------------
# Browsing rules
# ------------------------------------------------------------------
def test_session_starts_with_view_or_search() -> None:
    for session in SESSIONS:
        if session:
            assert session[0].event_type in (EventType.USER_VIEW, EventType.SEARCH)


def test_click_is_always_on_the_product_just_viewed() -> None:
    for session in SESSIONS:
        for previous, event in pairwise(session):
            if event.event_type is EventType.PRODUCT_CLICK:
                assert previous.event_type is EventType.USER_VIEW
                assert event.product_id == previous.product_id


def test_checkout_only_happens_with_items_in_the_cart() -> None:
    for event in all_events(EventType.CHECKOUT):
        assert event.quantity is not None and event.quantity > 0


def test_sessions_respect_the_length_limit() -> None:
    assert all(len(s) <= MAX_EVENTS_PER_SESSION for s in SESSIONS)


def test_funnel_narrows_at_every_step() -> None:
    def reached(step: EventType) -> int:
        return sum(step in types(s) for s in SESSIONS)

    funnel = [
        reached(EventType.USER_VIEW),
        reached(EventType.ADD_TO_CART),
        reached(EventType.CHECKOUT),
        reached(EventType.PURCHASE),
        reached(EventType.PAYMENT_SUCCESS),
    ]
    assert funnel == sorted(funnel, reverse=True)
    assert funnel[-1] > 0


# ------------------------------------------------------------------
# Orders & payments
# ------------------------------------------------------------------
def test_cart_to_items_merges_repeated_products() -> None:
    book = Product("p_1", "books", Decimal("10.00"))
    toy = Product("p_2", "toys", Decimal("3.00"))
    items = cart_to_items([(book, 1), (toy, 1), (book, 2)])

    assert [(i.product_id, i.quantity) for i in items] == [("p_1", 3), ("p_2", 1)]


def test_purchase_items_match_the_cart_contents() -> None:
    for session in SESSIONS:
        cart: list[tuple[str, int]] = []
        for event in session:
            if event.event_type is EventType.ADD_TO_CART:
                cart.append((event.product_id, event.quantity))
            elif event.event_type is EventType.REMOVE_FROM_CART:
                cart.pop()
            elif event.event_type is EventType.PURCHASE:
                expected: dict[str, int] = {}
                for product_id, quantity in cart:
                    expected[product_id] = expected.get(product_id, 0) + quantity
                assert {i.product_id: i.quantity for i in event.items} == expected


def test_payment_follows_purchase_for_the_same_order() -> None:
    for session in SESSIONS:
        for previous, event in pairwise(session):
            if event.event_type in (EventType.PAYMENT_SUCCESS, EventType.PAYMENT_FAILED):
                assert previous.event_type is EventType.PURCHASE
                assert event.order_id == previous.order_id
                assert event.order_amount == previous.order_amount


def test_only_failed_payments_have_a_failure_reason() -> None:
    assert all(e.failure_reason for e in all_events(EventType.PAYMENT_FAILED))
    assert all(e.failure_reason is None for e in all_events(EventType.PAYMENT_SUCCESS))


def test_payment_failure_rate_is_close_to_configured_value() -> None:
    failed = len(all_events(EventType.PAYMENT_FAILED))
    succeeded = len(all_events(EventType.PAYMENT_SUCCESS))
    assert 0.04 < failed / (failed + succeeded) < 0.12  # configured: 8%
