"""Product catalog with a realistic long-tail popularity distribution."""

from __future__ import annotations

import random
from dataclasses import dataclass
from decimal import Decimal
from itertools import accumulate

# Price range per category, in whole currency units (min, max).
CATEGORY_PRICE_RANGES: dict[str, tuple[int, int]] = {
    "electronics": (50, 1500),
    "computers": (300, 3000),
    "appliances": (40, 1200),
    "apparel": (10, 200),
    "shoes": (30, 250),
    "beauty": (5, 120),
    "home": (10, 400),
    "sports": (10, 600),
    "toys": (5, 150),
    "books": (5, 60),
}


@dataclass(frozen=True, slots=True)
class Product:
    product_id: str
    category: str
    price: Decimal


class Catalog:
    """A fixed set of products: a few are very popular, most are rarely seen."""

    def __init__(self, size: int = 2000, zipf_exponent: float = 1.1, seed: int = 42) -> None:
        if size <= 0:
            raise ValueError("size must be positive")

        rng = random.Random(seed)
        categories = list(CATEGORY_PRICE_RANGES)
        self.products: list[Product] = [
            _make_product(index, rng.choice(categories), rng) for index in range(size)
        ]

        # Product at rank r (0-based) gets weight 1 / (r + 1) ** s  -> Zipf long tail.
        weights = [1 / (rank + 1) ** zipf_exponent for rank in range(size)]
        self._cum_weights = list(accumulate(weights))

    def __len__(self) -> int:
        return len(self.products)

    def sample(self, rng: random.Random) -> Product:
        """Pick one product, favouring popular ones."""
        return rng.choices(self.products, cum_weights=self._cum_weights, k=1)[0]


def _make_product(index: int, category: str, rng: random.Random) -> Product:
    low, high = CATEGORY_PRICE_RANGES[category]
    cents = rng.randint(low * 100, high * 100)
    return Product(
        product_id=f"p_{index:05d}",
        category=category,
        price=(Decimal(cents) / 100).quantize(Decimal("0.01")),
    )
