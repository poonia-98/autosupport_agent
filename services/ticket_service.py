import re
import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog
from arq.connections import ArqRedis

from core.exceptions import InvalidStateTransition, TicketNotFound
from core.metrics import ticket_created
from db import store
from domain.bus import bus
from domain.events import TicketClosed, TicketCreated, TicketResolved
from domain.ticket import validate_transition

logger = structlog.get_logger("services.ticket")

# Explicit allowlist — callers cannot mass-assign arbitrary columns
_UPDATE_FIELDS = {"title", "description", "priority", "category", "status"}


async def create(
    pool: asyncpg.Pool,
    arq: ArqRedis,
    data: dict[str, Any],
    actor: dict,
) -> dict[str, Any]:
    # idempotency check
    idem_key = data.get("idempotency_key")
    if idem_key:
        existing = await store.get_ticket_by_idempotency_key(pool, idem_key)
        if existing:
            logger.info("ticket.idempotent_hit", ticket_id=existing["id"])
            return existing

    ticket_id     = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())

    ticket_data = {
        "title":           data["title"],
        "description":     data.get("description", ""),
        "priority":        data.get("priority", "medium"),
        "category":        data.get("category", "general"),
        "source":          data.get("source", "api"),
        "user_id":         data.get("user_id") or (actor.get("sub") if actor.get("sub") not in {None, "system"} else None),
        "idempotency_key": idem_key,
    }

    try:
        await store.insert_ticket(pool, ticket_id, ticket_data)
    except asyncpg.UniqueViolationError:
        if idem_key:
            existing = await store.get_ticket_by_idempotency_key(pool, idem_key)
            if existing:
                logger.info("ticket.idempotent_conflict_hit", ticket_id=existing["id"])
                return existing
        raise

    # enqueue classification in ARQ
    job = await arq.enqueue_job(
        "classify_ticket",
        ticket_id      = ticket_id,
        correlation_id = correlation_id,
    )
    job_id = job.job_id if job else ticket_id

    await store.upsert_job_status(pool, job_id, ticket_id, "enqueued")
    await store.audit(
        pool, actor["sub"], actor["email"],
        "ticket.create", "ticket", ticket_id,
        {"priority": ticket_data["priority"], "category": ticket_data["category"]},
    )
    await store.syslog(pool, "INFO", "ticket_service", f"created {ticket_id}")

    ticket_created.labels(priority=ticket_data["priority"]).inc()

    await bus.emit(TicketCreated(
        ticket_id      = ticket_id,
        priority       = ticket_data["priority"],
        category       = ticket_data["category"],
        source         = ticket_data["source"],
        correlation_id = correlation_id,
    ))

    ticket = await store.get_ticket(pool, ticket_id)
    return ticket  # type: ignore[return-value]


async def update(
    pool: asyncpg.Pool,
    ticket_id: str,
    data: dict[str, Any],
    actor: dict,
) -> dict[str, Any]:
    ticket = await store.get_ticket(pool, ticket_id)
    if not ticket:
        raise TicketNotFound(ticket_id)

    updates = {k: v for k, v in data.items() if k in _UPDATE_FIELDS and v is not None}

    # validate status transition
    if "status" in updates:
        validate_transition(ticket["status"], updates["status"])

    if not updates:
        return ticket

    async with pool.acquire() as conn:
        async with conn.transaction():
            # re-read inside transaction for status CAS
            if "status" in updates:
                ok = await store.transition_ticket_status(
                    conn, ticket_id, ticket["status"], updates.pop("status")
                )
                if not ok:
                    raise InvalidStateTransition(ticket["status"], data.get("status", ""))
            if updates:
                await store.update_ticket(conn, ticket_id, updates)
            await store.audit(
                conn, actor["sub"], actor["email"],
                "ticket.update", "ticket", ticket_id, updates,
            )

    updated = await store.get_ticket(pool, ticket_id)
    return updated  # type: ignore[return-value]


async def resolve(
    pool: asyncpg.Pool,
    ticket_id: str,
    actor: dict,
) -> dict[str, Any]:
    ticket = await store.get_ticket(pool, ticket_id)
    if not ticket:
        raise TicketNotFound(ticket_id)

    validate_transition(ticket["status"], "resolved")

    async with pool.acquire() as conn:
        async with conn.transaction():
            ok = await store.transition_ticket_status(conn, ticket_id, ticket["status"], "resolved")
            if not ok:
                raise InvalidStateTransition(ticket["status"], "resolved")
            await store.update_ticket(conn, ticket_id, {"resolved_at": datetime.now(UTC)})
            await store.audit(conn, actor["sub"], actor["email"], "ticket.resolve", "ticket", ticket_id)

    await bus.emit(TicketResolved(
        ticket_id      = ticket_id,
        resolved_by    = actor["email"],
        correlation_id = str(uuid.uuid4()),
    ))

    return await store.get_ticket(pool, ticket_id)  # type: ignore[return-value]


async def bulk_close(
    pool: asyncpg.Pool,
    ticket_ids: list[str],
    actor: dict,
) -> dict[str, Any]:
    async with pool.acquire() as conn:
        closed_count, missing = await store.bulk_close_tickets(conn, ticket_ids)
        await store.audit(
            conn, actor["sub"], actor["email"],
            "ticket.bulk_close", "ticket", None,
            {"ids": ticket_ids, "closed": closed_count},
        )

    for tid in ticket_ids:
        if tid not in missing:
            await bus.emit(TicketClosed(ticket_id=tid, correlation_id=str(uuid.uuid4())))

    return {"closed": closed_count, "not_found": missing}


async def get_page(
    pool: asyncpg.Pool,
    limit: int = 50,
    offset: int = 0,
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    search: str | None = None,
) -> dict[str, Any]:
    if search and re.fullmatch(r"\s*(?i:(and|or|not)(?:\s+(and|or|not))*)\s*", search):
        from fastapi import HTTPException
        from fastapi import status as http_status
        raise HTTPException(http_status.HTTP_400_BAD_REQUEST, detail="Invalid search query.")

    try:
        items, total = await store.get_tickets_page(
            pool, limit=limit, offset=offset,
            status=status, priority=priority, category=category, search=search,
        )
    except Exception as exc:
        # FTS parse errors become 400 at the API layer
        if "syntax error" in str(exc).lower() or "unterminated" in str(exc).lower():
            from fastapi import HTTPException
            from fastapi import status as http_status
            raise HTTPException(http_status.HTTP_400_BAD_REQUEST, detail=f"Invalid search query: {exc}")
        raise

    return {"items": items, "total": total, "limit": limit, "offset": offset}
