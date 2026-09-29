# Real-Time Data Platform for E-commerce Analytics

> 🚧 **Work in progress** — built milestone by milestone. See [Roadmap](#roadmap).

A production-style data platform that ingests a continuous stream of e-commerce events,
processes them in real time, and models them into an analytics warehouse — with data
quality, orchestration, testing, observability, and CI/CD treated as first-class concerns.

## Why this project

A fictional mid-size e-commerce company, **ShopStream**, needs two kinds of numbers:

| Consumer | Question | Freshness | Priority |
|---|---|---|---|
| Operations | Is the payment failure rate spiking right now? | < 1 min | Speed |
| Growth | How is the funnel converting by traffic source? | minutes – daily | Speed + depth |
| Finance | What was yesterday's exact GMV? | T+1 | **Correctness** |

This drives the core design principle:

> **The streaming layer is fast but provisional. The batch warehouse is slower but the source of truth.**

## Architecture (V1)

```
Event Generator (Python)
        │
        ▼
Kafka  ── user_events · purchase_events · inventory_events · dead_letter_events
        │
        ▼
Spark Structured Streaming
   ├─► Bronze Parquet   (raw, immutable, replayable)
   ├─► Silver Parquet   (validated, deduplicated)  ──► Quarantine (+ failure_reason)
   └─► PostgreSQL realtime.*  (windowed metrics, idempotent upserts)
        │
        ▼
Airflow (daily) ─► load Silver ─► dbt build ─► data quality checks ─► summary
        │
        ▼
PostgreSQL warehouse (star schema) ─► Grafana dashboards
```

## Tech Stack

| Layer | Technology |
|---|---|
| Ingestion | Apache Kafka (KRaft) |
| Stream processing | Spark Structured Streaming (PySpark) |
| Storage | Parquet (data lake), PostgreSQL (serving + warehouse) |
| Transformation | dbt |
| Orchestration | Apache Airflow |
| Observability | Python structured logging, Prometheus, Grafana |
| Quality | pytest, dbt tests, custom data quality layer |
| Infra / DevOps | Docker Compose, GitHub Actions, AWS (S3, RDS, EC2, IAM, CloudWatch) |

## Roadmap

- [ ] **M1** — Project foundation: structure, tooling, logging, Docker Compose, CI
- [ ] **M2** — Event generator with realistic funnels and fault injection
- [ ] **M3** — Kafka: topics, partitioning strategy, delivery semantics
- [ ] **M4** — Streaming ingestion: Bronze / Silver / Quarantine, deduplication, checkpointing
- [ ] **M5** — Real-time windowed aggregations to PostgreSQL
- [ ] **M6** — Warehouse modelling: star schema, idempotent loads
- [ ] **M7** — dbt: staging → intermediate → marts, incremental models, tests
- [ ] **M8** — Airflow: daily DAG, retries, backfill
- [ ] **M9** — Observability, integration tests, CI hardening
- [ ] **M10** — AWS migration, documentation, performance & failure analysis

## Getting Started

_Coming in M1._

## Project Structure

_Coming in M1._

## Design Decisions

Architecture Decision Records will live in [`docs/adr/`](docs/adr/).