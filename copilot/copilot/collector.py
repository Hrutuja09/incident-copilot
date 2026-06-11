import structlog

from copilot.schemas import RawSignals, Window

logger = structlog.get_logger()


def collect(window: Window) -> RawSignals:
    logger.info(
        "collector called",
        start=window.start.isoformat(),
        end=window.end.isoformat(),
    )
    return RawSignals(logs=[], metrics=[], window=window)
