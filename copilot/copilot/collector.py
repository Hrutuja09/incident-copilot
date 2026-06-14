import json
import os
from datetime import UTC, datetime
from pathlib import Path

import structlog

from copilot.prometheus_client import PrometheusClient
from copilot.schemas import LogEntry, MetricSeries, RawSignals, Window

logger = structlog.get_logger()

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
DEFAULT_LOG_FILE_PATH = "../logs/sample_app.jsonl"

METRIC_QUERIES: list[tuple[str, str]] = [
    ("error_rate", 'rate(http_requests_total{status_code=~"4..|5.."}[1m])'),
    (
        "p95_latency",
        "histogram_quantile(0.95, rate(http_request_duration_seconds_bucket[1m]))",
    ),
    ("request_rate", "rate(http_requests_total[1m])"),
    ("db_healthy", "db_healthy"),
]

_LOG_ENTRY_FIELDS = (
    "timestamp",
    "level",
    "service",
    "endpoint",
    "latency_ms",
    "status_code",
    "message",
)


def _log_file_path() -> Path:
    relative = os.getenv("LOG_FILE_PATH", DEFAULT_LOG_FILE_PATH)
    return (PROJECT_ROOT / relative).resolve()


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


def _to_log_entry(obj: dict) -> LogEntry | None:
    missing = [field for field in _LOG_ENTRY_FIELDS if field not in obj]
    if missing:
        return None

    timestamp = _parse_timestamp(obj["timestamp"])
    if timestamp is None:
        return None

    try:
        return LogEntry(
            timestamp=timestamp,
            level=str(obj["level"]),
            service=str(obj["service"]),
            endpoint=str(obj["endpoint"]),
            latency_ms=float(obj["latency_ms"]),
            status_code=int(obj["status_code"]),
            message=str(obj["message"]),
        )
    except (TypeError, ValueError):
        return None


def _read_logs(window: Window) -> list[LogEntry]:
    path = _log_file_path()
    entries: list[LogEntry] = []
    buffered_start = _ensure_utc(window.buffered_start)
    window_end = _ensure_utc(window.end)

    try:
        with path.open(encoding="utf-8", errors="replace") as handle:
            for line_no, line in enumerate(handle, 1):
                stripped = line.strip()
                if not stripped:
                    continue

                try:
                    obj = json.loads(stripped)
                except json.JSONDecodeError:
                    logger.warning(
                        "skipping malformed jsonl line",
                        path=str(path),
                        line_no=line_no,
                    )
                    continue

                if not isinstance(obj, dict):
                    logger.warning(
                        "skipping non-object jsonl line",
                        path=str(path),
                        line_no=line_no,
                    )
                    continue

                entry = _to_log_entry(obj)
                if entry is None:
                    logger.warning(
                        "skipping invalid log entry",
                        path=str(path),
                        line_no=line_no,
                    )
                    continue

                if buffered_start <= entry.timestamp <= window_end:
                    entries.append(entry)
    except FileNotFoundError:
        logger.warning("log file not found", path=str(path))

    return entries


def _fetch_metrics(window: Window, client: PrometheusClient) -> list[MetricSeries]:
    series: list[MetricSeries] = []

    for name, query in METRIC_QUERIES:
        result = client.query_range(query, window.buffered_start, window.end)
        series.append(
            MetricSeries(
                name=name,
                timestamps=result.timestamps,
                values=result.values,
                data_available=result.data_available,
            )
        )

    return series


def collect(window: Window) -> RawSignals:
    client = PrometheusClient()

    log_entries = _read_logs(window)
    metric_series = _fetch_metrics(window, client)

    logger.info(
        "collection complete",
        log_count=len(log_entries),
        metric_series_count=len(metric_series),
        buffered_start=window.buffered_start.isoformat(),
        window_end=window.end.isoformat(),
    )

    return RawSignals(logs=log_entries, metrics=metric_series, window=window)
