from enum import Enum

from pydantic import BaseModel, Field


class TicketStatus(str, Enum):
    OPEN        = "open"
    IN_PROGRESS = "in_progress"
    ESCALATED   = "escalated"
    SLA_BREACHED = "sla_breached"
    RESOLVED    = "resolved"
    CLOSED      = "closed"


class TicketPriority(str, Enum):
    LOW      = "low"
    MEDIUM   = "medium"
    HIGH     = "high"
    CRITICAL = "critical"


class TicketCategory(str, Enum):
    TECHNICAL       = "technical"
    BILLING         = "billing"
    BUG             = "bug"
    FEATURE_REQUEST = "feature_request"
    GENERAL         = "general"


class CreateTicketRequest(BaseModel):
    title:           str = Field(..., min_length=3, max_length=255)
    description:     str = Field(default="", max_length=10_000)
    priority:        TicketPriority = TicketPriority.MEDIUM
    category:        TicketCategory = TicketCategory.GENERAL
    idempotency_key: str | None = Field(default=None, max_length=64)
    source:          str | None = Field(default="api", max_length=32)


class UpdateTicketRequest(BaseModel):
    title:       str | None = Field(default=None, min_length=3, max_length=255)
    description: str | None = Field(default=None, max_length=10_000)
    priority:    TicketPriority | None = None
    category:    TicketCategory | None = None
    status:      TicketStatus | None   = None


class BulkCloseRequest(BaseModel):
    ticket_ids: list[str] = Field(..., min_length=1, max_length=100)
