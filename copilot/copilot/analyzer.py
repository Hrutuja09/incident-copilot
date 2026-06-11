import structlog

from copilot.schemas import RCAReport

logger = structlog.get_logger()


def analyze(context: str) -> RCAReport:
    logger.info("analyzer called")
    return RCAReport(
        cause="stub — analyzer not yet implemented",
        confidence=0.0,
        evidence=["no evidence collected"],
        next_steps=["implement real analyzer on Day 5"],
    )
