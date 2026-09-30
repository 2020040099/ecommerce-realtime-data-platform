"""Smoke tests: verify the development environment itself is correct."""

import sys

import pytest


@pytest.mark.unit
def test_python_version_is_312_or_newer() -> None:
    assert sys.version_info >= (3, 12), f"Expected Python 3.12+, got {sys.version}"
