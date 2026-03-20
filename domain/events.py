import time
from dataclasses import dataclass, field


@dataclass(frozen=True)
class TicketCreated:
    ticket_id: str
    priority: str
    category: str
    source: str
    correlation_id: str
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TicketClassified:
    ticket_id: str
    category: str
    priority: str
    assigned_team: str
    correlation_id: str
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TicketEscalated:
    ticket_id: str
    level: int  # 1=notify, 2=page
    reason: str
    correlation_id: str
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TicketResolved:
    ticket_id: str
    resolved_by: str
    correlation_id: str
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class TicketClosed:
    ticket_id: str
    correlation_id: str
    ts: float = field(default_factory=time.time)


@dataclass(frozen=True)
class SLABreached:
    ticket_id: str
    priority: str
    breached_at: float
    correlation_id: str
    ts: float = field(default_factory=time.time)

