from enum import Enum

from pydantic import BaseModel


class SLASeverity(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class SLAThresholds(BaseModel):
    first_response_seconds: int
    resolution_seconds: int


DEFAULT_SLA: dict[SLASeverity, SLAThresholds] = {
    SLASeverity.CRITICAL: SLAThresholds(first_response_seconds=900, resolution_seconds=14_400),
    SLASeverity.HIGH: SLAThresholds(first_response_seconds=3_600, resolution_seconds=28_800),
    SLASeverity.MEDIUM: SLAThresholds(first_response_seconds=14_400, resolution_seconds=86_400),
    SLASeverity.LOW: SLAThresholds(first_response_seconds=86_400, resolution_seconds=259_200),
}


class SLAMetrics(BaseModel):
    ticket_id: str
    severity: SLASeverity
    response_time_seconds: int | None = None
    resolution_time_seconds: int | None = None
    response_sla_breached: bool = False
    resolution_sla_breached: bool = False
    response_time_remaining_seconds: int | None = None

