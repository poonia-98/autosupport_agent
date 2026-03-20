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


class StageExecutionError(Exception):
    def __init__(self, agent: str, duration_ms: int, original: Exception):
        super().__init__(f"{agent} failed: {original}")
        self.agent = agent
        self.duration_ms = duration_ms
        self.original = original


def _elapsed_ms(started_at: float) -> int:
    return max(int((time.monotonic() - started_at) * 1000), 1)


async def run_pipeline(ticket_data: dict[str, Any], correlation_id: str | None = None) -> dict[str, Any]:
    """
    Runs the 5-agent pipeline against ticket_data.
    Returns a merged dict of all agent outputs.
    """
    ticket_id     = ticket_data.get("id", "unknown")
    correlation   = correlation_id or str(uuid.uuid4())
    ml_signals: dict[str, Any] = {}
    agent_trace: dict[str, dict[str, Any]] = {}

    pipeline_start = time.monotonic()

    # -- classifier
    classification, classifier_ms = await _run_stage("ticket_classifier", ticket_classifier.run, ticket_data)
    agent_trace["ticket_classifier"] = {
        "status": "ok",
        "duration_ms": classifier_ms,
        "output": classification,
    }

    # -- priority
    priority, priority_ms = await _run_stage(
        "priority_predictor", priority_predictor.run, ticket_data, classification, ml_signals
    )
    agent_trace["priority_predictor"] = {
        "status": "ok",
        "duration_ms": priority_ms,
        "output": priority,
    }

    # -- escalation
    escalation, escalation_ms = await _run_stage(
        "escalation_detector", escalation_detector.run, ticket_data, classification, ml_signals
    )
    agent_trace["escalation_detector"] = {
        "status": "ok",
        "duration_ms": escalation_ms,
        "output": escalation,
    }

    # -- response
    response, response_ms = await _run_stage(
        "response_suggester", response_suggester.run, ticket_data, classification, escalation
    )
    agent_trace["response_suggester"] = {
        "status": "ok",
        "duration_ms": response_ms,
        "output": response,
    }

    # -- routing
    routing, routing_ms = await _run_stage(
        "auto_router", auto_router.run, ticket_data, classification, escalation
    )
    agent_trace["auto_router"] = {
        "status": "ok",
        "duration_ms": routing_ms,
        "output": routing,
    }

    pipeline_duration_seconds = time.monotonic() - pipeline_start
    pipeline_duration.observe(pipeline_duration_seconds)

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
        "agent_trace":         agent_trace,
        "pipeline_duration_ms": max(int(pipeline_duration_seconds * 1000), 1),
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


async def _run_stage(agent: str, runner, *args):
    t0 = time.monotonic()
    try:
        result = await runner(*args)
    except Exception as exc:
        duration_ms = _elapsed_ms(t0)
        agent_duration.labels(agent=agent).observe(max(duration_ms, 1) / 1000)
        raise StageExecutionError(agent, duration_ms, exc) from exc
    duration_ms = _elapsed_ms(t0)
    agent_duration.labels(agent=agent).observe(max(duration_ms, 1) / 1000)
    return result, duration_ms
