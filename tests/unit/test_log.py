"""Unit tests for platform_common.log."""

from __future__ import annotations

import json
import logging
import sys
import time
from collections.abc import Iterator
from datetime import datetime
from decimal import Decimal
from typing import Any

import pytest
from platform_common.log import JsonFormatter, configure_logging

pytestmark = pytest.mark.unit


# ------------------------------------------------------------------
# Helpers & fixtures
# ------------------------------------------------------------------
def make_record(**overrides: Any) -> logging.LogRecord:
    """Build a deterministic LogRecord, created at the Unix epoch (1970-01-01 UTC)."""
    attrs: dict[str, Any] = {
        "name": "test.logger",
        "levelname": "INFO",
        "levelno": logging.INFO,
        "msg": "event_produced",
        "created": 0.0,
        "component": "unit-test",
    }
    attrs.update(overrides)
    return logging.makeLogRecord(attrs)


def format_json(record: logging.LogRecord) -> dict[str, Any]:
    return json.loads(JsonFormatter().format(record))


def read_json_lines(capsys: pytest.CaptureFixture[str]) -> list[dict[str, Any]]:
    return [json.loads(line) for line in capsys.readouterr().out.splitlines()]


@pytest.fixture(autouse=True)
def isolated_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    """Each test starts with no LOG_* env vars and leaves the root logger clean."""
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    yield
    root = logging.getLogger()
    root.handlers.clear()
    root.setLevel(logging.WARNING)


# ------------------------------------------------------------------
# JsonFormatter — pure, no global state
# ------------------------------------------------------------------
def test_core_fields_present() -> None:
    out = format_json(make_record())
    assert out["level"] == "INFO"
    assert out["component"] == "unit-test"
    assert out["logger"] == "test.logger"
    assert out["event"] == "event_produced"


def test_timestamp_is_iso8601_utc() -> None:
    out = format_json(make_record(created=0.0))
    assert out["timestamp"] == "1970-01-01T00:00:00.000+00:00"


def test_missing_component_defaults_to_unknown() -> None:
    out = format_json(logging.makeLogRecord({"msg": "no_component"}))
    assert out["component"] == "unknown"


def test_extra_fields_are_included() -> None:
    out = format_json(make_record(event_id="abc-123", topic="user_events"))
    assert out["event_id"] == "abc-123"
    assert out["topic"] == "user_events"


def test_extra_fields_cannot_override_core_fields() -> None:
    out = format_json(make_record(level="HACKED"))
    assert out["level"] == "INFO"


def test_non_json_types_do_not_crash() -> None:
    out = format_json(make_record(amount=Decimal("19.99"), seen_at=datetime(2026, 1, 1)))
    assert out["amount"] == "19.99"
    assert out["seen_at"] == "2026-01-01 00:00:00"


def test_exception_rendered_in_error_field() -> None:
    try:
        raise ValueError("bad price")
    except ValueError:
        record = make_record(levelname="ERROR", levelno=logging.ERROR, exc_info=sys.exc_info())
    out = format_json(record)
    assert "Traceback" in out["error"]
    assert "ValueError: bad price" in out["error"]


# ------------------------------------------------------------------
# configure_logging — end-to-end through the root logger
# ------------------------------------------------------------------
def test_emits_json_with_component_and_extra(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(component="generator")
    logging.getLogger("generator.producer").info("event_produced", extra={"event_id": "e1"})

    [line] = read_json_lines(capsys)  # exactly one line, or this unpacking fails
    assert line["component"] == "generator"
    assert line["logger"] == "generator.producer"
    assert line["event_id"] == "e1"


def test_default_level_is_info(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(component="c")
    log = logging.getLogger("t")
    log.debug("hidden")
    log.info("shown")

    assert [rec["event"] for rec in read_json_lines(capsys)] == ["shown"]


def test_log_level_env_var_is_respected(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging(component="c")
    logging.getLogger("t").debug("now_visible")

    assert read_json_lines(capsys)[0]["event"] == "now_visible"


def test_explicit_argument_overrides_env_var(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("LOG_LEVEL", "DEBUG")
    configure_logging(component="c", level="WARNING")
    logging.getLogger("t").info("suppressed")

    assert capsys.readouterr().out == ""


def test_is_idempotent(capsys: pytest.CaptureFixture[str]) -> None:
    configure_logging(component="c")
    configure_logging(component="c")
    logging.getLogger("t").info("once")

    assert len(read_json_lines(capsys)) == 1


def test_text_format_is_utc_even_on_non_utc_machine(monkeypatch: pytest.MonkeyPatch) -> None:
    # CI runners are UTC already, so force a non-UTC zone or this test could never fail.
    monkeypatch.setenv("TZ", "Asia/Shanghai")
    time.tzset()
    try:
        configure_logging(component="c", fmt="text")
        formatter = logging.getLogger().handlers[0].formatter
        assert formatter is not None

        line = formatter.format(make_record(created=0.0))
        assert line.startswith("1970-01-01 00:00:00")  # would be 08:00:00 if local time
        assert "Z | INFO" in line
    finally:
        monkeypatch.undo()
        time.tzset()


def test_invalid_format_raises() -> None:
    with pytest.raises(ValueError, match="fmt must be one of"):
        configure_logging(component="c", fmt="xml")
