import structlog

from copilot.schemas import LogEntry, MetricSeries, RawSignals

logger = structlog.get_logger()

TOKEN_BUDGET = 2000
CHARS_PER_TOKEN = 4
ERROR_LEVELS = frozenset({"error", "critical"})


def _summarize_metric(series: MetricSeries) -> str:
    if not series.values:
        if series.data_available:
            return f"{series.name}: 0.000 (no errors during window)"
        return f"{series.name}: no data available (instrumentation gap)"

    minimum = min(series.values)
    maximum = max(series.values)
    mean = sum(series.values) / len(series.values)
    summary = f"{series.name}: min={minimum:.3f} max={maximum:.3f} mean={mean:.3f}"

    if series.name == "db_healthy" and any(value == 0.0 for value in series.values):
        summary += "\nWARNING: db_healthy dropped to 0 during window"
    elif any(value == 0.0 for value in series.values):
        summary += f"\nNOTE: {series.name} hit 0 during window"

    return summary


def _sample_evenly(entries: list[LogEntry], count: int) -> list[LogEntry]:
    if not entries or count <= 0:
        return []
    if len(entries) <= count:
        return entries

    step = (len(entries) - 1) / (count - 1)
    indices = {round(index * step) for index in range(count)}
    return [entries[index] for index in sorted(indices)]


def _logs_to_json(entries: list[LogEntry]) -> str:
    if not entries:
        return "none"
    return "\n".join(entry.model_dump_json() for entry in entries)


def _assemble_context(
    signals: RawSignals,
    error_logs: list[LogEntry],
    normal_sample: list[LogEntry],
    normal_log_total: int,
) -> str:
    metric_summaries = "\n".join(
        _summarize_metric(series) for series in signals.metrics
    )

    return (
        "=== INCIDENT WINDOW ===\n"
        f"Start: {signals.window.buffered_start.isoformat()}\n"
        f"End: {signals.window.end.isoformat()}\n"
        "\n"
        "=== METRICS SUMMARY ===\n"
        f"{metric_summaries}\n"
        "\n"
        f"=== ERROR LOGS ({len(error_logs)} total) ===\n"
        f"{_logs_to_json(error_logs)}\n"
        "\n"
        f"=== NORMAL LOG SAMPLE ({len(normal_sample)} of {normal_log_total}) ===\n"
        f"{_logs_to_json(normal_sample)}"
    )


def _estimate_tokens(text: str) -> int:
    return len(text) // CHARS_PER_TOKEN


def build(signals: RawSignals) -> str:
    error_logs = [
        entry for entry in signals.logs if entry.level.lower() in ERROR_LEVELS
    ]
    normal_logs = [
        entry for entry in signals.logs if entry.level.lower() not in ERROR_LEVELS
    ]

    normal_sample = _sample_evenly(normal_logs, 5)
    context = _assemble_context(
        signals, error_logs, normal_sample, len(normal_logs)
    )

    if _estimate_tokens(context) > TOKEN_BUDGET:
        error_logs = error_logs[:20]
        normal_sample = _sample_evenly(normal_logs, 3)
        context = _assemble_context(
            signals, error_logs, normal_sample, len(normal_logs)
        )

    estimated_tokens = _estimate_tokens(context)
    logger.info(
        "context built",
        estimated_tokens=estimated_tokens,
        error_count=len(error_logs),
        normal_sample_count=len(normal_sample),
    )

    return context
