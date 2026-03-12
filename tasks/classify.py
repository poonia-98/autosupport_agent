"""
ARQ task definitions.

Each function is an ARQ job — called by the ARQ worker process,
not the API process. ctx['pool'] is an asyncpg pool initialised
in WorkerSettings.on_startup.
"""

import uuid
from typing import Any

import structlog

from core.logging import bind_job_context, clear_context
from db import store
from domain.bus import bus
from domain.events import TicketCreated
from workflows.engine import run_pipeline

logger = structlog.get_logger("tasks.classify")


async def classify_ticket(
    ctx: dict,
    ticket_id: str,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """
    Main classification job. Runs the 5-agent pipeline and persists results.
    Idempotent: if ticket is already classified (assigned_team set), no-op.
    """
    correlation = correlation_id or str(uuid.uuid4())
    clear_context()
    bind_job_context(
        job_id         = ctx.get("job_id", "unknown"),
        correlation_id = correlation,
        task           = "classify_ticket",
    )

    pool = ctx["pool"]

    ticket = await store.get_ticket(pool, ticket_id)
    if not ticket:
        logger.warning("classify.ticket_not_found", ticket_id=ticket_id)
        await store.upsert_job_status(pool, ctx.get("job_id", ticket_id), ticket_id, "failed", "ticket not found")
        return {"ok": False, "reason": "not_found"}

    if ticket.get("assigned_team"):
        logger.info("classify.already_done", ticket_id=ticket_id)
        await store.upsert_job_status(pool, ctx.get("job_id", ticket_id), ticket_id, "skipped")
        return {"ok": True, "reason": "already_classified"}

    await store.upsert_job_status(pool, ctx.get("job_id", ticket_id), ticket_id, "running")

    try:
        result = await run_pipeline(ticket, correlation_id=correlation)
    except Exception as exc:
        logger.exception("classify.pipeline_error", ticket_id=ticket_id)
        await store.upsert_job_status(pool, ctx.get("job_id", ticket_id), ticket_id, "failed", str(exc))
        raise  # let ARQ retry

    updates: dict[str, Any] = {}
    if result.get("assigned_team"):
        updates["assigned_team"] = result["assigned_team"]
    if result.get("assigned_to"):
        updates["assigned_to"] = result["assigned_to"]
    if result.get("suggested_response"):
        updates["suggested_response"] = result["suggested_response"]
    predicted = result.get("predicted_priority")
    if predicted and predicted != ticket.get("priority"):
        updates["priority"] = predicted
    if result.get("intent"):
        updates["category"] = result["intent"]
    if result.get("should_escalate") or result.get("escalation", {}).get("should_escalate"):
        updates["status"] = "escalated"

    if updates:
        await store.update_ticket(pool, ticket_id, updates)

    # record per-agent timings
    for agent_name in ("ticket_classifier", "priority_predictor", "escalation_detector", "response_suggester", "auto_router"):
        await store.record_agent_event(pool, ticket_id, agent_name, result, 0)

    await store.upsert_job_status(pool, ctx.get("job_id", ticket_id), ticket_id, "done")
    await store.syslog(pool, "INFO", "tasks.classify", f"classified ticket {ticket_id}")

    logger.info(
        "classify.done",
        ticket_id = ticket_id,
        category  = result.get("intent"),
        priority  = result.get("predicted_priority"),
        team      = result.get("assigned_team"),
    )
    return {"ok": True, "ticket_id": ticket_id}
