"""Structured logging shared by every platform component.

Usage — once, at the entrypoint of a service:

    from platform_common import configure_logging
    configure_logging(component="generator")

Then, in any module:

    import logging
    logger = logging.getLogger(__name__)
    logger.info("event_produced", extra={"event_id": "abc-123", "topic": "user_events"})
"""

from __future__ import annotations

import json
import logging
import os
import sys
import time
from datetime import UTC, datetime
from typing import Any

# Every attribute a plain LogRecord carries. Anything NOT in this set was
# supplied by the caller via `extra=...` and should be emitted as a JSON field.
_STANDARD_RECORD_ATTRS = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {
    "message",
    "asctime",
    "component",
}

_TEXT_FORMAT = "%(asctime)sZ | %(levelname)-8s | %(component)s | %(name)s | %(message)s"

VALID_FORMATS = ("json", "text")


class ComponentFilter(logging.Filter):
    """Stamp every record with the name of the component that emitted it."""

    def __init__(self, component: str) -> None:
        super().__init__()
        self.component = component

    def filter(self, record: logging.LogRecord) -> bool:
        record.component = self.component
        return True


class JsonFormatter(logging.Formatter):
    """Render a LogRecord as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.fromtimestamp(record.created, tz=UTC).isoformat(
                timespec="milliseconds"
            ),
            "level": record.levelname,
            "component": getattr(record, "component", "unknown"),
            "logger": record.name,
            "event": record.getMessage(),
        }

        # Caller-supplied context (extra=...). Core fields above always win.
        for key, value in record.__dict__.items():
            if key not in _STANDARD_RECORD_ATTRS:
                payload.setdefault(key, value)

        if record.exc_info:
            payload["error"] = self.formatException(record.exc_info)

        return json.dumps(payload, default=str, ensure_ascii=False)


def configure_logging(
    component: str,
    level: str | None = None,
    fmt: str | None = None,
) -> None:
    """Configure the root logger. Call exactly once per process, at startup.

    Args:
        component: Logical service name, e.g. "generator" or "streaming".
        level: Log level name. Falls back to env var LOG_LEVEL, then "INFO".
        fmt: "json" (machines) or "text" (humans; omits `extra` fields). Falls
        back to env var LOG_FORMAT, then "json".
    """
    resolved_level = (level or os.getenv("LOG_LEVEL", "INFO")).upper()
    resolved_fmt = (fmt or os.getenv("LOG_FORMAT", "json")).lower()
    if resolved_fmt not in VALID_FORMATS:
        raise ValueError(f"fmt must be one of {VALID_FORMATS}, got {resolved_fmt!r}")

    handler = logging.StreamHandler(sys.stdout)
    handler.addFilter(ComponentFilter(component))
    if resolved_fmt == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter(_TEXT_FORMAT)
        formatter.converter = time.gmtime  # always UTC, same as the JSON formatter
    handler.setFormatter(formatter)

    root = logging.getLogger()
    root.handlers.clear()  # idempotent: calling twice must not duplicate output
    root.addHandler(handler)
    root.setLevel(resolved_level)
