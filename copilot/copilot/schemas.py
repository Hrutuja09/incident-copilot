from datetime import datetime, timedelta
from typing import Self

from pydantic import BaseModel, Field, computed_field, model_validator


class Window(BaseModel):
    start: datetime
    end: datetime
    lookback_seconds: int = 300

    @model_validator(mode="after")
    def end_after_start(self) -> Self:
        if self.end <= self.start:
            raise ValueError("end must be after start")
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def buffered_start(self) -> datetime:
        return self.start - timedelta(seconds=self.lookback_seconds)


class LogEntry(BaseModel):
    timestamp: datetime
    level: str
    service: str
    endpoint: str
    latency_ms: float
    status_code: int
    message: str


class MetricSeries(BaseModel):
    name: str
    timestamps: list[datetime]
    values: list[float]
    data_available: bool = True


class RawSignals(BaseModel):
    logs: list[LogEntry]
    metrics: list[MetricSeries]
    window: Window


class RCAReport(BaseModel):
    cause: str
    confidence: float = Field(ge=0, le=1)
    evidence: list[str]
    next_steps: list[str]
