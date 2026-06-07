AI Incident Copilot
An LLM-powered triage tool that diagnoses infrastructure outages from a time window alone — no symptom hints provided to the model.
Given a start and end timestamp, it collects logs and metrics, builds a token-budgeted context, and asks Claude to propose a root cause with supporting evidence and next steps.

How it works.
Sample App — a FastAPI service backed by Postgres that emits structured JSON logs and Prometheus metrics
Collector — pulls logs and metrics for the incident window (with a lookback buffer, because causes precede symptoms)
Context Builder — filters noise and fits the most informative signal into a token budget
LLM Analyzer — calls the Claude API with a structured prompt and returns a typed RCA report

Note: The model receives only the time window. No symptom hints. It figures out what broke, not just why.

What we are using
Stack
Python 3.12,
FastAPI
DatabasePostgreSQL (SQLAlchemy + asyncpg)
Logging structlog (structured JSON → JSONL file)
Metrics Prometheus
Analysis Claude API (Anthropic)
Infrastructure Docker, docker-compose