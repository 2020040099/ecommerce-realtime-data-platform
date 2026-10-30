"""Sinks: where outgoing records end up.

Every sink has the same shape: write records one at a time, then close.
The generator only talks to this interface, so switching from a file to
Kafka later (M3) means adding a new sink, not changing the generator.
"""

import sys
from pathlib import Path
from types import TracebackType
from typing import Self, TextIO

from generator.faults import OutgoingRecord


class Sink:
    """Base class for all sinks. Use it with `with` so close() always runs."""

    def write(self, record: OutgoingRecord) -> None:
        raise NotImplementedError

    def close(self) -> None:
        """Release resources. Default: nothing to release."""

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class StdoutSink(Sink):
    """Writes one payload per line to stdout (or a given stream)."""

    def __init__(self, stream: TextIO | None = None) -> None:
        self._stream = stream or sys.stdout

    def write(self, record: OutgoingRecord) -> None:
        self._stream.write(record.payload + "\n")

    def close(self) -> None:
        self._stream.flush()  # don't close stdout - we don't own it


class JsonlFileSink(Sink):
    """Writes one payload per line to a JSON Lines file (overwrites it)."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        # Not a `with` block on purpose: the file must stay open across many
        # write() calls. close() (called by __exit__) closes it.
        self._file = self.path.open("w", encoding="utf-8")  # noqa: SIM115

    def write(self, record: OutgoingRecord) -> None:
        self._file.write(record.payload + "\n")

    def close(self) -> None:
        self._file.close()
