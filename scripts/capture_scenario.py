#!/usr/bin/env python3
"""Capture a fault scenario: baseline traffic, inject fault, save logs and metrics."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

PROJECT_ROOT = Path(__file__).resolve().parent.parent
LOG_FILE = PROJECT_ROOT / "sample_app/logs/sample_app.jsonl"
SCENARIOS_DIR = PROJECT_ROOT / "scenarios"
SAMPLE_APP_URL = "http://localhost:8000"
PROMETHEUS_URL = "http://localhost:9090"
POSTGRES_CONTAINER = "incident-copilot-postgres-1"

BASELINE_SECONDS = 120
FAULT_DURATION_SECONDS = 60
LOOKBACK_SECONDS = 300
POST_FAULT_SETTLE_SECONDS = 15
DB_RESTORE_WAIT_SECONDS = 5

SCENARIOS = (
    "db_down",
    "memory_exhaustion",
    "dependency_timeout",
    "bad_deploy",
)

IN_APP_FAULTS = {
    "memory_exhaustion",
    "dependency_timeout",
    "bad_deploy",
}

METRIC_QUERIES: list[tuple[str, str]] = [
    ("error_rate", 'rate(http_requests_total{status_code=~"4..|5.."}[1m])'),
    (
        "p95_latency",
        "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[1m]))",
    ),
    ("request_rate", "rate(http_requests_total[1m])"),
    ("db_healthy", "db_healthy"),
    ("process_memory_bytes", "process_memory_bytes"),
    (
        "downstream_p95_latency",
        "histogram_quantile(0.95, rate(downstream_request_duration_seconds_bucket[1m]))",
    ),
    (
        "downstream_timeout_rate",
        "rate(downstream_timeouts_total[1m])",
    ),
]


def _ensure_utc(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC)


def _parse_timestamp(raw: object) -> datetime | None:
    if isinstance(raw, (int, float)):
        return datetime.fromtimestamp(raw, tz=UTC)

    if isinstance(raw, str):
        normalized = raw.replace("Z", "+00:00")
        try:
            parsed = datetime.fromisoformat(normalized)
        except ValueError:
            return None
        return _ensure_utc(parsed)

    return None


def check_services() -> None:
    for url in (f"{SAMPLE_APP_URL}/health", "http://localhost:8001/health"):
        try:
            with httpx.Client(timeout=5.0) as client:
                response = client.get(url)
                response.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"Service check failed for {url}: {exc}", file=sys.stderr)
            print("Run 'make up' first.", file=sys.stderr)
            sys.exit(1)


def start_traffic() -> subprocess.Popen[bytes]:
    print("Starting traffic generator")
    return subprocess.Popen(
        [sys.executable, str(PROJECT_ROOT / "loadgen/run.py")],
        cwd=PROJECT_ROOT,
    )


def stop_traffic(process: subprocess.Popen[bytes]) -> None:
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)
    print("Traffic generator stopped")


def establish_baseline() -> None:
    for remaining in range(BASELINE_SECONDS, 0, -30):
        print(f"Establishing baseline... {remaining}s remaining")
        time.sleep(30)
    print("Baseline established")


def _run_docker(args: list[str]) -> None:
    try:
        subprocess.run(
            ["docker", *args],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError:
        print("docker not found — is Docker installed and on PATH?", file=sys.stderr)
        sys.exit(1)
    except subprocess.CalledProcessError as exc:
        print(exc.stderr or exc.stdout or str(exc), file=sys.stderr)
        sys.exit(1)


def _activate_in_app_fault(fault_type: str) -> None:
    payload = json.dumps({"duration_seconds": FAULT_DURATION_SECONDS}).encode()
    request = urllib.request.Request(
        f"{SAMPLE_APP_URL}/admin/faults/{fault_type}",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=10) as response:
            if response.status != 200:
                raise RuntimeError(f"unexpected status {response.status}")
    except urllib.error.URLError as exc:
        print(f"failed to activate fault {fault_type}: {exc}", file=sys.stderr)
        sys.exit(1)


def inject_fault(scenario: str) -> dict[str, object]:
    incident_start = datetime.now(UTC)
    print(f"Injecting fault: {scenario} at {incident_start.isoformat()}")

    if scenario == "db_down":
        _run_docker(["stop", POSTGRES_CONTAINER])
        for remaining in range(FAULT_DURATION_SECONDS, 0, -10):
            print(f"Postgres down... {remaining}s remaining")
            time.sleep(10)
        _run_docker(["start", POSTGRES_CONTAINER])
        print("Postgres restored; waiting for readiness")
        time.sleep(DB_RESTORE_WAIT_SECONDS)
    elif scenario in IN_APP_FAULTS:
        _activate_in_app_fault(scenario)
        for remaining in range(FAULT_DURATION_SECONDS, 0, -10):
            print(f"Fault active... {remaining}s remaining")
            time.sleep(10)
    else:
        raise ValueError(f"unknown scenario: {scenario}")

    incident_end = datetime.now(UTC)
    print(f"Fault window ended at {incident_end.isoformat()}")

    return {
        "fault_type": scenario,
        "start": incident_start.isoformat(),
        "end": incident_end.isoformat(),
        "duration_seconds": FAULT_DURATION_SECONDS,
        "lookback_seconds": LOOKBACK_SECONDS,
    }


def capture_logs(buffered_start: datetime, window_end: datetime) -> list[str]:
    lines: list[str] = []
    if not LOG_FILE.exists():
        print(f"Warning: log file not found at {LOG_FILE}", file=sys.stderr)
        return lines

    with LOG_FILE.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            stripped = line.strip()
            if not stripped:
                continue

            try:
                obj = json.loads(stripped)
            except json.JSONDecodeError:
                continue

            if not isinstance(obj, dict):
                continue

            timestamp = _parse_timestamp(obj.get("timestamp"))
            if timestamp is None:
                continue

            if buffered_start <= timestamp <= window_end:
                lines.append(stripped)

    return lines


def _query_prometheus(
    client: httpx.Client, query: str, start: datetime, end: datetime
) -> dict[str, object]:
    unavailable = {
        "query": query,
        "timestamps": [],
        "values": [],
        "data_available": False,
    }

    try:
        response = client.get(
            f"{PROMETHEUS_URL}/api/v1/query_range",
            params={
                "query": query,
                "start": start.timestamp(),
                "end": end.timestamp(),
                "step": "15s",
            },
        )
        response.raise_for_status()
        body = response.json()
    except httpx.HTTPError:
        return unavailable

    if body.get("status") != "success":
        return unavailable

    try:
        result = body["data"]["result"]
        if not result:
            return {
                "query": query,
                "timestamps": [],
                "values": [],
                "data_available": True,
            }

        values = result[0]["values"]
        timestamps = [
            datetime.fromtimestamp(float(pair[0]), tz=UTC).isoformat()
            for pair in values
        ]
        parsed_values = [float(pair[1]) for pair in values]
    except (KeyError, IndexError, TypeError, ValueError):
        return unavailable

    return {
        "query": query,
        "timestamps": timestamps,
        "values": parsed_values,
        "data_available": True,
    }


def capture_metrics(buffered_start: datetime, window_end: datetime) -> list[dict[str, object]]:
    series: list[dict[str, object]] = []

    with httpx.Client(timeout=10.0) as client:
        for name, query in METRIC_QUERIES:
            result = _query_prometheus(client, query, buffered_start, window_end)
            result["name"] = name
            series.append(result)

    return series


def write_scenario(scenario: str, window: dict[str, object]) -> None:
    start = _ensure_utc(datetime.fromisoformat(str(window["start"])))
    end = _ensure_utc(datetime.fromisoformat(str(window["end"])))
    lookback_seconds = int(window["lookback_seconds"])
    buffered_start = start - timedelta(seconds=lookback_seconds)

    output_dir = SCENARIOS_DIR / scenario
    output_dir.mkdir(parents=True, exist_ok=True)

    log_lines = capture_logs(buffered_start, end)
    metrics = capture_metrics(buffered_start, end)

    logs_path = output_dir / "logs.jsonl"
    metrics_path = output_dir / "metrics.json"
    window_path = output_dir / "window.json"

    with logs_path.open("w", encoding="utf-8") as handle:
        for line in log_lines:
            handle.write(f"{line}\n")

    metrics_path.write_text(
        json.dumps({"metrics": metrics}, indent=2) + "\n",
        encoding="utf-8",
    )
    window_path.write_text(json.dumps(window, indent=2) + "\n", encoding="utf-8")

    print(f"Wrote {logs_path} ({len(log_lines)} log lines)")
    print(f"Wrote {metrics_path} ({len(metrics)} metric series)")
    print(f"Wrote {window_path}")
    print(
        "Capture window: "
        f"{buffered_start.isoformat()} to {end.isoformat()} "
        f"(incident {start.isoformat()} to {end.isoformat()}, "
        f"lookback {lookback_seconds}s)"
    )


def run_scenario(scenario: str) -> None:
    print("=" * 40)
    print(f"Capturing scenario: {scenario}")
    print("=" * 40)

    traffic = start_traffic()
    try:
        establish_baseline()
        window = inject_fault(scenario)
        print(f"Waiting {POST_FAULT_SETTLE_SECONDS}s for system to stabilize")
        time.sleep(POST_FAULT_SETTLE_SECONDS)
    finally:
        stop_traffic(traffic)

    write_scenario(scenario, window)
    print(f"Scenario capture complete: {scenario}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Capture logs and metrics for a fault scenario."
    )
    parser.add_argument(
        "scenario",
        nargs="?",
        choices=SCENARIOS,
        help="Fault scenario to capture",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Capture all scenarios sequentially",
    )
    args = parser.parse_args()

    if args.all:
        selected = list(SCENARIOS)
    elif args.scenario:
        selected = [args.scenario]
    else:
        parser.error("provide a scenario name or --all")

    check_services()

    for index, scenario in enumerate(selected):
        run_scenario(scenario)
        if index < len(selected) - 1:
            print("Waiting 30s before next scenario")
            time.sleep(30)


if __name__ == "__main__":
    main()
