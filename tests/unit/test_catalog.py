"""Unit tests for generator.catalog."""

import random
from collections import Counter

import pytest
from generator.catalog import CATEGORY_PRICE_RANGES, Catalog

pytestmark = pytest.mark.unit


def test_catalog_has_requested_size() -> None:
    assert len(Catalog(size=500)) == 500


def test_product_ids_are_unique() -> None:
    ids = [p.product_id for p in Catalog().products]
    assert len(ids) == len(set(ids))


def test_same_seed_builds_identical_catalog() -> None:
    assert Catalog(seed=7).products == Catalog(seed=7).products


def test_different_seed_builds_different_catalog() -> None:
    assert Catalog(seed=7).products != Catalog(seed=8).products


def test_every_product_has_a_known_category_and_valid_price() -> None:
    for product in Catalog().products:
        low, high = CATEGORY_PRICE_RANGES[product.category]
        assert low <= product.price <= high
        assert product.price.as_tuple().exponent == -2  # exactly two decimal places


def test_sampling_is_reproducible_with_the_same_rng_seed() -> None:
    catalog = Catalog()
    first = [catalog.sample(random.Random(123)).product_id for _ in range(1)]
    rng_a, rng_b = random.Random(123), random.Random(123)
    run_a = [catalog.sample(rng_a).product_id for _ in range(50)]
    run_b = [catalog.sample(rng_b).product_id for _ in range(50)]
    assert run_a == run_b
    assert first[0] == run_a[0]


def test_popularity_follows_a_long_tail() -> None:
    catalog = Catalog(size=2000)
    rng = random.Random(0)
    counts = Counter(catalog.sample(rng).product_id for _ in range(20_000))

    top_1_percent = sum(n for _, n in counts.most_common(20))
    assert top_1_percent / 20_000 > 0.40  # a handful of products dominate


def test_invalid_size_is_rejected() -> None:
    with pytest.raises(ValueError):
        Catalog(size=0)
