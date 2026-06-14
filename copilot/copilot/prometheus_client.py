from datetime import UTC, datetime

import httpx
import structlog

from copilot.schemas import MetricSeries

logger = structlog.get_logger()


class PrometheusClient:
    def __init__(self, base_url: str = "http://prometheus:9090", timeout: float = 10.0) -> None:
        self.base_url = base_url.rstrip("/")
        self._timeout = timeout

    def query_range(
        self,
        query: str,
        start: datetime,
        end: datetime,
        step: str = "15s",
    ) -> MetricSeries:
        unavailable = MetricSeries(
            name=query, timestamps=[], values=[], data_available=False
        )
        empty_success = MetricSeries(
            name=query, timestamps=[], values=[], data_available=True
        )

        try:
            with httpx.Client(timeout=self._timeout) as client:
                response = client.get(
                    f"{self.base_url}/api/v1/query_range",
                    params={
                        "query": query,
                        "start": start.timestamp(),
                        "end": end.timestamp(),
                        "step": step,
                    },
                )
                response.raise_for_status()
                body = response.json()
        except Exception as exc:
            logger.warning(
                "prometheus query_range failed",
                query=query,
                error=str(exc),
            )
            return unavailable

        if body.get("status") != "success":
            logger.warning(
                "prometheus query_range error",
                query=query,
                error=body.get("error", "unknown error"),
            )
            return unavailable

        try:
            result = body["data"]["result"]
            if not result:
                return empty_success

            values = result[0]["values"]
            if not values:
                return empty_success

            timestamps = [
                datetime.fromtimestamp(float(pair[0]), tz=UTC) for pair in values
            ]
            parsed_values = [float(pair[1]) for pair in values]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            logger.warning(
                "prometheus query_range malformed response",
                query=query,
                error=str(exc),
            )
            return unavailable

        return MetricSeries(
            name=query,
            timestamps=timestamps,
            values=parsed_values,
            data_available=True,
        )
