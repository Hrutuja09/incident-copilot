import structlog

from copilot.schemas import RawSignals

logger = structlog.get_logger()


def build(signals: RawSignals) -> str:
    logger.info("context_builder called")
    return "stub context — no real signals yet"
