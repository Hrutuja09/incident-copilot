# AI Incident Copilot

An LLM-powered triage tool that diagnoses infrastructure outages from a time window alone — no symptom hints provided to the model.

Given a start and end timestamp, it collects logs and metrics, builds a token-budgeted context, and asks Claude to classify the incident, propose a root cause with supporting evidence, and suggest next steps.

> **Note:** The model receives only the time window. No symptom hints. It figures out what broke, not just why.

## How it works

| Component | Status | Description |
|-----------|--------|-------------|
| **Sample App** | Done | FastAPI service backed by Postgres that emits structured JSON logs and Prometheus metrics |
| **Collector** | Done | Pulls logs from JSONL and metrics from Prometheus for the incident window (with a lookback buffer) |
| **Context Builder** | Done | Filters noise, summarizes metrics, and fits signal into a ~2000-token budget |
| **LLM Analyzer** | Done | Calls Claude with a structured prompt and returns a typed RCA report with a root-cause category |

### Pipeline

```
POST /investigate { start, end }
        │
        ▼
   Collector ──► logs (JSONL) + metrics (Prometheus query_range)
        │
        ▼
 Context Builder ──► structured text (metrics summary, error logs, normal log sample)
        │
        ▼
   LLM Analyzer ──► RCAReport { root_cause_category, cause, confidence, evidence, next_steps }
```

## Project structure

```
incident-copilot/
├── pyproject.toml              # uv workspace (sample_app + copilot)
├── docker-compose.yml          # Postgres, sample_app, Prometheus, copilot
├── Makefile                    # up / down / logs / seed / traffic / investigate / demo
├── .env                        # ANTHROPIC_API_KEY (not committed)
├── scripts/
│   └── demo.sh                 # End-to-end automated demo (baseline, fault, diagnosis)
├── faults/
│   ├── db_down.py              # Stop/start Postgres to simulate an outage
│   └── last_incident.json      # Written by db_down.py; used by demo and manual runs
├── prometheus/
│   └── prometheus.yml          # Scrapes sample_app /metrics every 5s
├── loadgen/
│   └── run.py                  # Simple load generator (~10 rps)
├── sample_app/                 # Fake microservice to diagnose
│   ├── app/
│   │   ├── main.py             # FastAPI routes, middleware, DB health loop
│   │   ├── metrics.py          # Prometheus metric definitions
│   │   └── logging_config.py   # structlog → stdout + JSONL
│   ├── logs/sample_app.jsonl   # Structured request logs (gitignored)
│   ├── seed.py                 # Creates orders table + sample data
│   └── Dockerfile
└── copilot/                    # Triage engine
    ├── copilot/
    │   ├── main.py             # FastAPI service (POST /investigate)
    │   ├── schemas.py          # Window, LogEntry, MetricSeries, RootCauseCategory, RCAReport
    │   ├── collector.py        # Log + metric collection
    │   ├── prometheus_client.py
    │   ├── context_builder.py  # Token-budgeted context assembly
    │   ├── prompts.py          # RCA system prompt
    │   ├── llm.py              # Anthropic API client
    │   └── analyzer.py         # Parse LLM response → RCAReport
    └── Dockerfile
```

## Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12 |
| Web framework | FastAPI |
| Database | PostgreSQL (SQLAlchemy + asyncpg) |
| Logging | structlog (structured JSON → stdout + JSONL file) |
| Metrics | Prometheus (`prometheus-client`) |
| Analysis | Claude API (Anthropic, `claude-sonnet-4-6`) |
| Infrastructure | Docker, docker-compose, uv |

## Quick start

```bash
# Set your Anthropic API key (required for /investigate)
echo "ANTHROPIC_API_KEY=sk-..." > .env

# Start Postgres, sample_app, Prometheus, and copilot
make up

# Seed the database (wait ~10s after `make up` for Postgres to be ready)
make seed

# Generate traffic against the sample app
make traffic

# Run an investigation for the last 10 minutes
make investigate

# Run the full automated demo (baseline traffic, Postgres fault, diagnosis)
make demo

# Hit the APIs directly
curl http://localhost:8000/health
curl http://localhost:8000/order/1
curl http://localhost:8001/health

# Follow structured logs
make logs

# Stop everything
make down
```

### Services

| Service | URL | Purpose |
|---------|-----|---------|
| sample_app | http://localhost:8000 | FastAPI API + `/metrics` endpoint |
| copilot | http://localhost:8001 | Incident triage API (`POST /investigate`) |
| Prometheus | http://localhost:9090 | Metrics UI and query interface |
| Postgres | localhost:5432 | Database (`incidents`, user/pass `postgres`) |

## Sample App

A small order-lookup service that simulates a real microservice. It produces the observability data the copilot analyzes.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{"status": "ok"}` |
| GET | `/order/{order_id}` | Fetches an order from Postgres (404 if missing) |
| GET | `/metrics` | Prometheus scrape endpoint |

### Structured logging

Every HTTP request is logged as a single JSON line to **stdout** and `sample_app/logs/sample_app.jsonl` (mounted from the host and shared with the copilot container at `/logs/sample_app.jsonl`).

Fields: `timestamp` (ISO 8601 UTC), `level`, `message`, `service`, `endpoint`, `method`, `latency_ms`, `status_code`.

### Prometheus metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | `method`, `endpoint`, `status_code` | Total HTTP requests |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint` | Request latency (buckets: 10ms–2.5s) |
| `db_healthy` | Gauge | — | `1.0` when Postgres is reachable, `0.0` when not (checked every 10s) |

Prometheus scrapes `sample_app:8000/metrics` every 5 seconds (see `prometheus/prometheus.yml`).

## Copilot

The copilot service runs a three-stage pipeline for any time window you provide.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{"status": "ok", "service": "copilot"}` |
| POST | `/investigate` | Runs collect → build → analyze; returns an `RCAReport` |

### Request body (`Window`)

```json
{
  "start": "2026-06-13T15:00:00Z",
  "end": "2026-06-13T15:10:00Z",
  "lookback_seconds": 300
}
```

- `lookback_seconds` (default 300) extends collection back before `start` so causes that precede symptoms are included.
- The effective collection window is `[buffered_start, end]`.

### Response (`RCAReport`)

```json
{
  "root_cause_category": "DATABASE_UNAVAILABLE",
  "cause": "Postgres became unreachable during the incident window",
  "confidence": 0.85,
  "evidence": ["db_healthy dropped to 0.0 at 15:32:05", "error rate peaked at 2.1 req/s"],
  "next_steps": ["Check Postgres connection limits", "Review pool size configuration"]
}
```

### Root cause categories

Every report includes a required `root_cause_category` from the `RootCauseCategory` enum. The model must select exactly one value and justify it with cited evidence. If the data does not support a specific classification, it returns `INSUFFICIENT_SIGNAL` rather than guessing.

| Category | When to use |
|----------|-------------|
| `DATABASE_UNAVAILABLE` | Database unreachable, connection refused, or `db_healthy=0` |
| `MEMORY_EXHAUSTION` | OOM kills, memory pressure, or heap exhaustion in logs or metrics |
| `DEPENDENCY_TIMEOUT` | Upstream or downstream service timeouts or slow dependency calls |
| `BAD_DEPLOY` | Errors or regressions correlated with a recent deployment |
| `INSUFFICIENT_SIGNAL` | Evidence does not clearly support any of the above categories |

The free-text `cause`, `evidence`, and `next_steps` fields are unchanged and carry the detailed reasoning.

### Stage details

**Collector** reads `sample_app.jsonl` (configurable via `LOG_FILE_PATH`) and queries Prometheus for four metrics over the buffered window:

| Metric | PromQL |
|--------|--------|
| error_rate | `rate(http_requests_total{status_code=~"5.."}[1m])` |
| p95_latency | `histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[1m]))` |
| request_rate | `rate(http_requests_total[1m])` |
| db_healthy | `db_healthy` |

Missing logs or unreachable Prometheus degrade gracefully — the pipeline continues with partial data.

**Context Builder** assembles structured text with a metrics summary (min/max/mean, `db_healthy` warnings), all error/critical logs, and up to 5 evenly-spaced normal log samples. If the estimate exceeds ~2000 tokens, it truncates to 20 error logs and 3 normal samples.

**LLM Analyzer** sends the context to Claude with a strict JSON-only RCA prompt defined in `prompts.py`. The model must return a `root_cause_category` alongside the free-text fields. It retries once on parse failure and returns safe fallbacks (with `INSUFFICIENT_SIGNAL`) if the API or parsing fails.

### Environment variables

| Variable | Service | Description |
|----------|---------|-------------|
| `ANTHROPIC_API_KEY` | copilot | Required for LLM analysis |
| `LOG_FILE_PATH` | copilot | Path to JSONL log file (default in Docker: `/logs/sample_app.jsonl`) |

## Load generator

`loadgen/run.py` sends GET requests to `/order/{id}` at ~10 rps with ±20% jitter, picking random order IDs 1–10. Use it to generate traffic and metrics before running an investigation:

```bash
make traffic
```

## Fault injection

`faults/db_down.py` simulates a database outage by stopping the Postgres container for 60 seconds, then restarting it. It records the incident window to `faults/last_incident.json` for use by the demo script or manual investigations:

```bash
make incident-db
```

The incident file contains `start`, `end`, `duration_seconds`, `fault_type`, and `container` fields.

## Automated demo

`scripts/demo.sh` runs a full end-to-end demonstration without manual steps:

1. Verifies sample_app and copilot health endpoints
2. Starts the load generator in the background
3. Waits 2 minutes to establish a traffic baseline
4. Injects a Postgres fault via `faults/db_down.py`
5. Waits for recovery, then calls `POST /investigate` using timestamps from `faults/last_incident.json`
6. Prints the formatted RCA report and stops the load generator

Requires bash, curl, and Python 3 on the host (Git Bash on Windows). Run after `make up`:

```bash
make demo
```

## Makefile targets

| Target | Command |
|--------|---------|
| `make up` | `docker-compose up --build -d` |
| `make down` | `docker-compose down` |
| `make logs` | `tail -f sample_app/logs/sample_app.jsonl` |
| `make seed` | Run `seed.py` inside the sample_app container |
| `make traffic` | `uv run python loadgen/run.py` |
| `make investigate` | POST last 10 minutes to copilot `/investigate` |
| `make incident-db` | Stop Postgres for 60s and write `faults/last_incident.json` |
| `make demo` | Run `scripts/demo.sh` (baseline, fault injection, diagnosis) |
