"""Command-line entry point: `uv run generator --rate 200 --output stdout`."""

import argparse
import logging
import os
import random
from pathlib import Path

from platform_common import configure_logging

from generator.catalog import Catalog
from generator.faults import DEFAULT_FAULTS, FaultConfig
from generator.kafka_sink import KafkaSink
from generator.runner import run
from generator.sinks import JsonlFileSink, Sink, StdoutSink

logger = logging.getLogger(__name__)

DEFAULT_PATH = Path("data/events.jsonl")


def positive_float(text: str) -> float:
    value = float(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {text}")
    return value


def positive_int(text: str) -> int:
    value = int(text)
    if value <= 0:
        raise argparse.ArgumentTypeError(f"must be > 0, got {text}")
    return value


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="generator",
        description="Stream simulated ShopStream e-commerce events in real time.",
    )
    parser.add_argument(
        "--rate", type=positive_float, default=10.0, help="events per second (default: 10)"
    )
    parser.add_argument(
        "--output",
        choices=["stdout", "file", "kafka"],
        default="stdout",
        help="where to send events",
    )
    parser.add_argument(
        "--path", type=Path, default=DEFAULT_PATH, help=f"file for --output file ({DEFAULT_PATH})"
    )
    parser.add_argument(
        "--bootstrap-servers",
        default=os.getenv("KAFKA_BOOTSTRAP_SERVERS", "localhost:9092"),
        help="Kafka address for --output kafka (env: KAFKA_BOOTSTRAP_SERVERS)",
    )
    parser.add_argument(
        "--max-events",
        type=positive_int,
        default=None,
        help="stop after N events (default: Ctrl+C)",
    )
    parser.add_argument("--seed", type=int, default=None, help="random seed for a reproducible run")
    parser.add_argument("--no-faults", action="store_true", help="emit only clean records")
    return parser


def make_sink(args: argparse.Namespace) -> Sink:
    if args.output == "file":
        return JsonlFileSink(args.path)
    if args.output == "kafka":
        return KafkaSink(args.bootstrap_servers)
    return StdoutSink()


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    configure_logging(component="generator")

    # `is not None`, not `or`: --seed 0 is a valid seed but falsy.
    seed = args.seed if args.seed is not None else random.randrange(2**32)
    faults = FaultConfig.none() if args.no_faults else DEFAULT_FAULTS

    logger.info(
        "generator_started",
        extra={
            "rate": args.rate,
            "output": args.output,
            "path": str(args.path) if args.output == "file" else None,
            "bootstrap_servers": args.bootstrap_servers if args.output == "kafka" else None,
            "max_events": args.max_events,
            "seed": seed,
            "faults_enabled": not args.no_faults,
        },
    )

    with make_sink(args) as sink:
        stats = run(
            sink,
            random.Random(seed),
            args.rate,
            catalog=Catalog(),  # fixed seed: products must match dim_product later
            faults=faults,
            max_events=args.max_events,
        )

    logger.info(
        "generator_stopped",
        extra={
            "generated": stats.generated,
            "emitted": stats.emitted,
            "dropped": stats.dropped,
            "stopped_by_user": stats.stopped_by_user,
            "by_topic": dict(stats.by_topic),
            "by_fault": dict(stats.by_fault),
        },
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
