import logging
import os
import sys
from typing import Any

import structlog


def _rename_event_key(
    logger: Any,
    method: str,
    event_dict: dict[str, Any],
) -> dict[str, Any]:
    """Rename structlog's 'event' key to 'message' for consistency."""
    event_dict["message"] = event_dict.pop("event", "")
    return event_dict


def setup_logging() -> None:
    """
    Configure structlog to emit JSON to stdout and append to logs/sample_app.jsonl.

    Each line contains: timestamp, level, message, plus any bound fields
    (service, endpoint, latency_ms, status_code, etc.).
    """
    os.makedirs("logs", exist_ok=True)

    # Route through stdlib so we can fan out to multiple handlers
    root = logging.getLogger()
    root.setLevel(logging.INFO)

    # Suppress uvicorn's own access log; our middleware handles that
    logging.getLogger("uvicorn.access").propagate = False

    plain_fmt = logging.Formatter("%(message)s")

    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(plain_fmt)
    root.addHandler(stdout_handler)

    file_handler = logging.FileHandler(
        "logs/sample_app.jsonl", mode="a", encoding="utf-8"
    )
    file_handler.setFormatter(plain_fmt)
    root.addHandler(file_handler)

    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            _rename_event_key,
            structlog.processors.StackInfoRenderer(),
            structlog.processors.ExceptionRenderer(),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )
