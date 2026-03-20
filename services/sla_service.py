import time
from typing import Any

import asyncpg

from core.logging import get_logger
from db import store
from models.sla import DEFAULT_SLA, SLASeverity, SLAThresholds

logger = get_logger("services.sla")


def _thresholds(priority: str) -> SLAThresholds:
    try:
        sev = SLASeverity(priority)
    except ValueError:
        sev = SLASeverity.MEDIUM
    return DEFAULT_SLA[sev]


async def run_sla_sweep(pool: asyncpg.Pool) -> int:
    """
    Marks tickets where first_response window has elapsed.
    Does NOT change ticket status — only flips response_sla_breached.
    Returns number of tickets newly marked.
    """
    rows, _ = await store.get_tickets_page(
        pool,
        limit=1000,
        status=None,
        priority=None,
        category=None,
        search=None,
    )

    open_statuses = {"open", "in_progress", "escalated", "sla_breached"}
    now = time.time()
    count = 0

    for ticket in rows:
        if ticket.get("status") not in open_statuses:
            continue
        if ticket.get("response_sla_breached"):
            continue

        priority = ticket.get("priority", "medium")
        thresholds = _thresholds(priority)
        created_at = ticket.get("created_at")
        if not created_at:
            continue

        age_secs = now - (created_at if isinstance(created_at, float) else created_at)
        if age_secs >= thresholds.first_response_seconds:
            await store.update_ticket(pool, ticket["id"], {"response_sla_breached": True})
            count += 1

    if count:
        logger.info("sla_sweep.marked", count=count)
    return count


async def compute_metrics(ticket: dict[str, Any]) -> dict[str, Any]:
    priority = ticket.get("priority", "medium")
    thresholds = _thresholds(priority)
    created_at = ticket.get("created_at") or 0.0
    if not isinstance(created_at, float):
        created_at = float(created_at) if created_at else 0.0

    now = time.time()
    age = now - created_at

    response_remaining = thresholds.first_response_seconds - age

    resolved_at = ticket.get("resolved_at")
    resolution_secs = None
    if resolved_at:
        rt = resolved_at if isinstance(resolved_at, float) else float(resolved_at)
        resolution_secs = int(rt - created_at)

    return {
        "ticket_id": ticket["id"],
        "priority": priority,
        "response_sla_breached": bool(ticket.get("response_sla_breached")),
        "resolution_sla_breached": bool(resolved_at and (now - created_at) > thresholds.resolution_seconds),
        "response_time_remaining_seconds": int(response_remaining) if response_remaining > 0 else 0,
        "resolution_seconds": resolution_secs,
    }

