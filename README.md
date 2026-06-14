# AI Incident Copilot

An LLM-powered triage tool that diagnoses infrastructure outages from a time window alone — no symptom hints provided to the model.

Given a start and end timestamp, it collects logs and metrics, builds a token-budgeted context, and asks Claude to propose a root cause with supporting evidence and next steps.

> **Note:** The model receives only the time window. No symptom hints. It figures out what broke, not just why.

## How it works

| Component | Status | Description |
|-----------|--------|-------------|
| **Sample App** | Done | FastAPI service backed by Postgres that emits structured JSON logs and Prometheus metrics |
| **Collector** | Done | Pulls logs from JSONL and metrics from Prometheus for the incident window (with a lookback buffer) |
| **Context Builder** | Done | Filters noise, summarizes metrics, and fits signal into a ~2000-token budget |
| **LLM Analyzer** | Done | Calls Claude with a structured prompt and returns a typed RCA report |

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
   LLM Analyzer ──► RCAReport { cause, confidence, evidence, next_steps }
```

## Project structure

```
incident-copilot/
├── pyproject.toml              # uv workspace (sample_app + copilot)
├── docker-compose.yml          # Postgres, sample_app, Prometheus, copilot
├── Makefile                    # up / down / logs / seed / traffic / investigate
├── .env                        # ANTHROPIC_API_KEY (not committed)
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
    │   ├── schemas.py          # Window, LogEntry, MetricSeries, RCAReport
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
  "cause": "Postgres connection pool exhausted",
  "confidence": 0.85,
  "evidence": ["db_healthy dropped to 0.0 at 15:32:05", "error rate peaked at 2.1 req/s"],
  "next_steps": ["Check Postgres connection limits", "Review pool size configuration"]
}
```

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

**LLM Analyzer** sends the context to Claude with a strict JSON-only RCA prompt. It retries once on parse failure and returns safe fallbacks if the API or parsing fails.

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

## Makefile targets

| Target | Command |
|--------|---------|
| `make up` | `docker-compose up --build -d` |
| `make down` | `docker-compose down` |
| `make logs` | `tail -f sample_app/logs/sample_app.jsonl` |
| `make seed` | Run `seed.py` inside the sample_app container |
| `make traffic` | `uv run python loadgen/run.py` |
| `make investigate` | POST last 10 minutes to copilot `/investigate` |
