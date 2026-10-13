"""A single user's browsing session, modelled as a simple state machine."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from generator.catalog import CATEGORY_PRICE_RANGES, Catalog, Product
from generator.events import CURRENCY, Event, EventType, OrderItem, order_total

START = "start"
END = "end"

# From each state: the possible next states and their probabilities (each row sums to 1).
TRANSITIONS: dict[str, list[tuple[str, float]]] = {
    START: [(EventType.USER_VIEW, 0.7), (EventType.SEARCH, 0.3)],
    EventType.SEARCH: [(EventType.USER_VIEW, 0.8), (END, 0.2)],
    EventType.USER_VIEW: [
        (EventType.PRODUCT_CLICK, 0.4),
        (EventType.USER_VIEW, 0.3),
        (EventType.SEARCH, 0.1),
        (END, 0.2),
    ],
    EventType.PRODUCT_CLICK: [
        (EventType.ADD_TO_CART, 0.3),
        (EventType.USER_VIEW, 0.5),
        (END, 0.2),
    ],
    EventType.ADD_TO_CART: [
        (EventType.CHECKOUT, 0.4),
        (EventType.USER_VIEW, 0.35),
        (EventType.REMOVE_FROM_CART, 0.1),
        (END, 0.15),
    ],
    EventType.REMOVE_FROM_CART: [(EventType.USER_VIEW, 0.6), (END, 0.4)],
    EventType.CHECKOUT: [(EventType.PURCHASE, 0.85), (END, 0.15)],
    EventType.PURCHASE: [(EventType.PAYMENT_SUCCESS, 0.92), (EventType.PAYMENT_FAILED, 0.08)],
    EventType.PAYMENT_SUCCESS: [(END, 1.0)],
    EventType.PAYMENT_FAILED: [(END, 1.0)],
}

MAX_EVENTS_PER_SESSION = 50
MEAN_SECONDS_BETWEEN_EVENTS = 20.0

DEVICE_TYPES = ["web", "ios", "android"]
COUNTRIES = ["AU", "US", "GB", "SG", "CN", "DE", "JP"]
SOURCES = ["organic", "paid_ads", "email", "social", "direct"]
SEARCH_TERMS = list(CATEGORY_PRICE_RANGES)
PAYMENT_METHODS = ["card", "paypal", "apple_pay", "afterpay"]
PAYMENT_FAILURE_REASONS = ["insufficient_funds", "card_declined", "timeout", "fraud_suspected"]


@dataclass(frozen=True, slots=True)
class SessionContext:
    """Facts that stay the same for every event in one session."""

    user_id: str
    session_id: str
    device_type: str
    country: str
    source: str

    @classmethod
    def random(cls, rng: random.Random, user_id: str) -> SessionContext:
        return cls(
            user_id=user_id,
            session_id=f"s_{rng.getrandbits(64):016x}",
            device_type=rng.choice(DEVICE_TYPES),
            country=rng.choice(COUNTRIES),
            source=rng.choice(SOURCES),
        )


def simulate_session(
    catalog: Catalog,
    rng: random.Random,
    started_at: datetime,
    user_id: str,
) -> list[Event]:
    """Walk the state machine once and return every event the user produced."""
    ctx = SessionContext.random(rng, user_id)
    events: list[Event] = []
    state = START
    clock = started_at
    current: Product | None = None  # the product the user is looking at
    cart: list[tuple[Product, int]] = []  # (product, quantity)
    order_id: str | None = None
    items: tuple[OrderItem, ...] = ()

    while len(events) < MAX_EVENTS_PER_SESSION:
        state = _next_state(state, rng)
        if state == END:
            break

        clock += timedelta(seconds=rng.expovariate(1 / MEAN_SECONDS_BETWEEN_EVENTS))
        event_type = EventType(state)

        if event_type is EventType.USER_VIEW:
            current = catalog.sample(rng)
            events.append(_event(ctx, event_type, clock, product=current))
        elif event_type is EventType.PRODUCT_CLICK:
            events.append(_event(ctx, event_type, clock, product=current))
        elif event_type is EventType.SEARCH:
            events.append(_event(ctx, event_type, clock, search_query=rng.choice(SEARCH_TERMS)))
        elif event_type is EventType.ADD_TO_CART:
            quantity = rng.randint(1, 3)
            cart.append((current, quantity))
            events.append(_event(ctx, event_type, clock, product=current, quantity=quantity))
        elif event_type is EventType.REMOVE_FROM_CART:
            product, quantity = cart.pop()
            events.append(_event(ctx, event_type, clock, product=product, quantity=quantity))
        elif event_type is EventType.CHECKOUT:
            total_items = sum(quantity for _, quantity in cart)
            events.append(_event(ctx, event_type, clock, quantity=total_items))
        elif event_type is EventType.PURCHASE:
            order_id = f"o_{rng.getrandbits(48):012x}"
            items = cart_to_items(cart)
            events.append(
                _event(
                    ctx,
                    event_type,
                    clock,
                    order_id=order_id,
                    items=items,
                    order_amount=order_total(items),
                    currency=CURRENCY,
                )
            )
        elif event_type in (EventType.PAYMENT_SUCCESS, EventType.PAYMENT_FAILED):
            failed = event_type is EventType.PAYMENT_FAILED
            events.append(
                _event(
                    ctx,
                    event_type,
                    clock,
                    order_id=order_id,
                    order_amount=order_total(items),
                    currency=CURRENCY,
                    payment_id=f"pay_{rng.getrandbits(48):012x}",
                    payment_method=rng.choice(PAYMENT_METHODS),
                    failure_reason=rng.choice(PAYMENT_FAILURE_REASONS) if failed else None,
                )
            )

    return events


def cart_to_items(cart: list[tuple[Product, int]]) -> tuple[OrderItem, ...]:
    """Turn cart lines into order lines, merging repeated products into one line."""
    products: dict[str, Product] = {}
    quantities: dict[str, int] = {}
    for product, quantity in cart:
        products.setdefault(product.product_id, product)
        quantities[product.product_id] = quantities.get(product.product_id, 0) + quantity
    return tuple(
        OrderItem(
            product_id=product_id,
            category=product.category,
            unit_price=product.price,
            quantity=quantities[product_id],
        )
        for product_id, product in products.items()
    )


def _next_state(state: str, rng: random.Random) -> str:
    options = TRANSITIONS[state]
    next_states = [s for s, _ in options]
    probabilities = [p for _, p in options]
    return rng.choices(next_states, weights=probabilities, k=1)[0]


def _event(
    ctx: SessionContext,
    event_type: EventType,
    at: datetime,
    product: Product | None = None,
    **extra: Any,
) -> Event:
    product_fields: dict[str, Any] = {}
    if product is not None:
        product_fields = {
            "product_id": product.product_id,
            "category": product.category,
            "price": product.price,
        }
    return Event(
        event_type=event_type,
        event_timestamp=at,
        user_id=ctx.user_id,
        session_id=ctx.session_id,
        device_type=ctx.device_type,
        country=ctx.country,
        source=ctx.source,
        **product_fields,
        **extra,
    )
