import json
import os

import structlog
from anthropic import Anthropic

from copilot.prompts import RCA_PROMPT
from copilot.schemas import RootCauseCategory

logger = structlog.get_logger()

MODEL = "claude-sonnet-4-6"
MAX_TOKENS = 1000
TEMPERATURE = 0.1

_FALLBACK_RESPONSE = json.dumps(
    {
        "root_cause_category": RootCauseCategory.INSUFFICIENT_SIGNAL.value,
        "cause": "llm unavailable",
        "confidence": 0.0,
        "evidence": [],
        "next_steps": ["check anthropic api key and network connectivity"],
    }
)


def call_llm(context: str) -> str:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        logger.error("anthropic api key not set")
        return _FALLBACK_RESPONSE

    try:
        client = Anthropic(api_key=api_key)
        response = client.messages.create(
            model=MODEL,
            max_tokens=MAX_TOKENS,
            temperature=TEMPERATURE,
            system=RCA_PROMPT,
            messages=[{"role": "user", "content": context}],
        )
        return response.content[0].text
    except Exception as exc:
        logger.error("anthropic api call failed", error=str(exc))
        return _FALLBACK_RESPONSE
