import json
import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
from generator.cli import main

FAST = ["--rate", "1000", "--max-events", "20"]


@pytest.fixture(autouse=True)
def isolated_logging(monkeypatch: pytest.MonkeyPatch) -> Iterator[None]:
    monkeypatch.delenv("LOG_LEVEL", raising=False)
    monkeypatch.delenv("LOG_FORMAT", raising=False)
    yield
    logging.getLogger().handlers.clear()


def test_streams_clean_events_to_stdout(capsys: pytest.CaptureFixture[str]) -> None:
    assert main([*FAST, "--no-faults"]) == 0

    events = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert len(events) == 20
    assert all("event_id" in event for event in events)


def test_writes_events_to_a_file_and_keeps_stdout_empty(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "events.jsonl"
    assert main([*FAST, "--output", "file", "--path", str(path)]) == 0

    assert len(path.read_text().splitlines()) == 20
    assert capsys.readouterr().out == ""


def test_logs_config_on_start_and_stats_on_stop(capsys: pytest.CaptureFixture[str]) -> None:
    main([*FAST, "--seed", "123"])

    started, stopped = [json.loads(line) for line in capsys.readouterr().err.splitlines()]
    assert started["event"] == "generator_started"
    assert started["seed"] == 123
    assert stopped["event"] == "generator_stopped"
    assert stopped["emitted"] == 20
    assert stopped["generated"] == stopped["emitted"] + stopped["dropped"]


@pytest.mark.parametrize(
    "argv",
    [["--rate", "0"], ["--rate", "abc"], ["--output", "kafka"], ["--max-events", "0"]],
)
def test_rejects_invalid_arguments_with_exit_code_2(argv: list[str]) -> None:
    with pytest.raises(SystemExit) as exc_info:
        main(argv)
    assert exc_info.value.code == 2
