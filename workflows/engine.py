import time
import uuid
from typing import Any

import structlog

from core.metrics import agent_duration, pipeline_duration
from domain.bus import bus
from domain.events import TicketClassified, TicketEscalated
from plugins.signal_audit import plugin as signal_audit
from support_agents import (
    auto_router,
    escalation_detector,
    priority_predictor,
    response_suggester,
    ticket_classifier,
)

logger = structlog.get_logger("workflows.engine")


async def run_pipeline(ticket_data: dict[str, Any], correlation_id: str | None = None) -> dict[str, Any]:
    """
    Runs the 5-agent pipeline against ticket_data.
    Returns a merged dict of all agent outputs.
    """
    ticket_id     = ticket_data.get("id", "unknown")
    correlation   = correlation_id or str(uuid.uuid4())
    ml_signals: dict[str, Any] = {}

    pipeline_start = time.monotonic()

    # -- classifier
    t0             = time.monotonic()
    classification = await ticket_classifier.run(ticket_data)
    _record("ticket_classifier", t0)

    # -- priority
    t0       = time.monotonic()
    priority = await priority_predictor.run(ticket_data, classification, ml_signals)
    _record("priority_predictor", t0)

    # -- escalation
    t0         = time.monotonic()
    escalation = await escalation_detector.run(ticket_data, classification, ml_signals)
    _record("escalation_detector", t0)

    # -- response
    t0       = time.monotonic()
    response = await response_suggester.run(ticket_data, classification, escalation)
    _record("response_suggester", t0)

    # -- routing
    t0      = time.monotonic()
    routing = await auto_router.run(ticket_data, classification, escalation)
    _record("auto_router", t0)

    pipeline_duration.observe(time.monotonic() - pipeline_start)

    ctx = {
        "classification": classification,
        "priority":       priority,
        "escalation":     escalation,
        "response":       response,
        "routing":        routing,
    }
    audit = signal_audit.run(ticket_data, ctx)

    result = {
        **classification,
        **priority,
        "escalation":          escalation,
        "suggested_response":  response.get("suggested_response"),
        "actions":             response.get("actions", []),
        "assigned_team":       routing.get("assigned_team"),
        "assigned_to":         routing.get("assigned_engineer"),
        "routing_reason":      routing.get("routing_reason"),
        "audit":               audit,
    }

    # emit domain events — fire-and-forget, handlers must not block
    await bus.emit(TicketClassified(
        ticket_id     = ticket_id,
        category      = classification.get("intent", "general"),
        priority      = priority.get("predicted_priority", "medium"),
        assigned_team = routing.get("assigned_team", "tier1_support"),
        correlation_id = correlation,
    ))

    if escalation.get("should_escalate"):
        await bus.emit(TicketEscalated(
            ticket_id      = ticket_id,
            level          = escalation.get("escalation_level", 1),
            reason         = escalation.get("reason", ""),
            correlation_id = correlation,
        ))

    logger.info(
        "pipeline.done",
        ticket_id     = ticket_id,
        category      = result.get("intent"),
        priority      = result.get("predicted_priority"),
        escalated     = escalation.get("should_escalate"),
        audit_passed  = audit.get("audit_passed"),
    )
    return result


def _record(agent: str, t0: float) -> None:
    agent_duration.labels(agent=agent).observe(time.monotonic() - t0)
