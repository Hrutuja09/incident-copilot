import logging
import sys
import time

import structlog
from fastapi import FastAPI

from copilot.analyzer import analyze
from copilot.collector import collect
from copilot.context_builder import build
from copilot.schemas import RCAReport, Window


def setup_logging() -> None:
    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=logging.INFO)
    structlog.configure(
        processors=[
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso", utc=True),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


setup_logging()

logger = structlog.get_logger()
app = FastAPI(title="copilot")


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "service": "copilot"}


@app.post("/investigate", response_model=RCAReport)
def investigate(window: Window) -> RCAReport:
    pipeline_start = time.perf_counter()

    signals = collect(window)
    context = build(signals)
    report = analyze(context)

    duration_ms = round((time.perf_counter() - pipeline_start) * 1000, 2)
    logger.info("investigate complete", duration_ms=duration_ms)

    return report
