import json

import structlog

from copilot.llm import call_llm
from copilot.schemas import RCAReport, RootCauseCategory

logger = structlog.get_logger()

_PARSE_ERROR_REPORT = RCAReport(
    root_cause_category=RootCauseCategory.INSUFFICIENT_SIGNAL,
    cause="parse error — llm response was not valid json",
    confidence=0.0,
    evidence=[],
    next_steps=["retry with cleaner prompt"],
)


def _strip_fences(text: str) -> str:
    return text.replace("```json", "").replace("```", "").strip()


def _parse_report(text: str) -> RCAReport | None:
    try:
        return RCAReport.model_validate_json(_strip_fences(text))
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning("failed to parse llm response", error=str(exc))
        return None


def analyze(context: str) -> RCAReport:
    response = call_llm(context)
    report = _parse_report(response)
    if report is not None:
        return report

    logger.warning("retrying llm call after parse failure")
    retry_response = call_llm(context)
    report = _parse_report(retry_response)
    if report is not None:
        return report

    logger.warning("llm response parse failed after retry")
    return _PARSE_ERROR_REPORT
