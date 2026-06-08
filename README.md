# AI Incident Copilot

An LLM-powered triage tool that diagnoses infrastructure outages from a time window alone — no symptom hints provided to the model.

Given a start and end timestamp, it collects logs and metrics, builds a token-budgeted context, and asks Claude to propose a root cause with supporting evidence and next steps.

> **Note:** The model receives only the time window. No symptom hints. It figures out what broke, not just why.

## How it works

| Component | Status | Description |
|-----------|--------|-------------|
| **Sample App** | Done | FastAPI service backed by Postgres that emits structured JSON logs and Prometheus metrics |
| **Collector** | Planned | Pulls logs and metrics for the incident window (with a lookback buffer, because causes precede symptoms) |
| **Context Builder** | Planned | Filters noise and fits the most informative signal into a token budget |
| **LLM Analyzer** | Planned | Calls the Claude API with a structured prompt and returns a typed RCA report |

## Project structure

```
incident-copilot/
├── pyproject.toml          # uv workspace (sample_app + copilot)
├── docker-compose.yml      # Postgres, sample_app, Prometheus
├── Makefile                # up / down / logs / seed
├── prometheus/
│   └── prometheus.yml      # Scrapes sample_app /metrics every 5s
├── sample_app/             # Fake microservice to diagnose
│   ├── app/
│   │   ├── main.py         # FastAPI routes, middleware, DB health loop
│   │   ├── metrics.py      # Prometheus metric definitions
│   │   └── logging_config.py
│   ├── seed.py             # Creates orders table + sample data
│   └── Dockerfile
└── copilot/                # Scaffold only — triage engine coming next
    └── copilot/__init__.py
```

## Stack

| Layer | Technology |
|-------|------------|
| Language | Python 3.12 |
| Web framework | FastAPI |
| Database | PostgreSQL (SQLAlchemy + asyncpg) |
| Logging | structlog (structured JSON → stdout + JSONL file) |
| Metrics | Prometheus (`prometheus-client`) |
| Analysis | Claude API (Anthropic) — not wired yet |
| Infrastructure | Docker, docker-compose, uv |

## Quick start

```bash
# Start Postgres, sample_app, and Prometheus
make up

# Seed the database (wait ~10s after `make up` for Postgres to be ready)
make seed

# Hit the API
curl http://localhost:8000/health
curl http://localhost:8000/order/1

# Scrape metrics
curl http://localhost:8000/metrics

# Follow structured logs
make logs

# Stop everything
make down
```

### Services

| Service | URL | Purpose |
|---------|-----|---------|
| sample_app | http://localhost:8000 | FastAPI API + `/metrics` endpoint |
| Prometheus | http://localhost:9090 | Metrics UI and query interface |
| Postgres | localhost:5432 | Database (`incidents`, user/pass `postgres`) |

## Sample App

A small order-lookup service that simulates a real microservice. It produces the observability data the copilot will eventually analyze.

### Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/health` | Returns `{"status": "ok"}` |
| GET | `/order/{order_id}` | Fetches an order from Postgres (404 if missing) |
| GET | `/metrics` | Prometheus scrape endpoint |

### Structured logging

Every HTTP request is logged as a single JSON line to **stdout** and `sample_app/logs/sample_app.jsonl` (mounted from the host).

Fields: `timestamp` (ISO 8601 UTC), `level`, `message`, `service`, `endpoint`, `method`, `latency_ms`, `status_code`.

### Prometheus metrics

| Metric | Type | Labels | Description |
|--------|------|--------|-------------|
| `http_requests_total` | Counter | `method`, `endpoint`, `status_code` | Total HTTP requests |
| `http_request_duration_seconds` | Histogram | `method`, `endpoint` | Request latency (buckets: 10ms–2.5s) |
| `db_healthy` | Gauge | — | `1.0` when Postgres is reachable, `0.0` when not (checked every 10s) |

Prometheus scrapes `sample_app:8000/metrics` every 5 seconds (see `prometheus/prometheus.yml`).

## Copilot (coming soon)

The `copilot/` package is scaffolded but not yet implemented. It will:

1. **Collect** logs from `sample_app.jsonl` and metrics from Prometheus for a given time window
2. **Build** a compact, token-budgeted context from the collected signal
3. **Analyze** with Claude and return a structured root-cause report

## Makefile targets

| Target | Command |
|--------|---------|
| `make up` | `docker-compose up --build -d` |
| `make down` | `docker-compose down` |
| `make logs` | `tail -f sample_app/logs/sample_app.jsonl` |
| `make seed` | Run `seed.py` inside the sample_app container |
