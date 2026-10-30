import io
from datetime import UTC, datetime
from pathlib import Path

import pytest
from generator.events import Topic
from generator.faults import FaultType, OutgoingRecord
from generator.sinks import JsonlFileSink, StdoutSink


def make_record(payload: str, fault: FaultType | None = None) -> OutgoingRecord:
    return OutgoingRecord(
        payload=payload,
        produced_at=datetime(2026, 1, 1, tzinfo=UTC),
        topic=Topic.USER_EVENTS,
        fault=fault,
    )


def test_stdout_sink_writes_only_payloads_one_per_line(capsys: pytest.CaptureFixture[str]) -> None:
    with StdoutSink() as sink:
        sink.write(make_record('{"event_id": "e1"}'))
        sink.write(make_record('{"event_id": "e2"}', fault=FaultType.DUPLICATE))

    # Labels like "duplicate" must never leak into the data stream.
    assert capsys.readouterr().out == '{"event_id": "e1"}\n{"event_id": "e2"}\n'


def test_stdout_sink_can_write_to_custom_stream() -> None:
    buffer = io.StringIO()
    with StdoutSink(stream=buffer) as sink:
        sink.write(make_record("x"))

    assert buffer.getvalue() == "x\n"


def test_file_sink_writes_jsonl_and_creates_parent_dirs(tmp_path: Path) -> None:
    path = tmp_path / "nested" / "events.jsonl"
    with JsonlFileSink(path) as sink:
        sink.write(make_record('{"event_id": "e1"}'))
        sink.write(make_record('{"event_id": "e2"}'))

    assert path.read_text().splitlines() == ['{"event_id": "e1"}', '{"event_id": "e2"}']


def test_file_sink_overwrites_existing_file(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    path.write_text("old content\n")
    with JsonlFileSink(path) as sink:
        sink.write(make_record("new"))

    assert path.read_text() == "new\n"


def test_file_sink_keeps_data_written_before_an_error(tmp_path: Path) -> None:
    path = tmp_path / "events.jsonl"
    with pytest.raises(RuntimeError), JsonlFileSink(path) as sink:
        sink.write(make_record("saved"))
        raise RuntimeError("generator crashed")

    # __exit__ still ran close(), so the buffered line reached the disk.
    assert path.read_text() == "saved\n"
