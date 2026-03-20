import uuid
from datetime import UTC, datetime
from typing import Any

import asyncpg
import structlog

from core.exceptions import IntegrationError
from db import store
from integrations import get_adapter

logger = structlog.get_logger("services.integration")


async def create(
    pool: asyncpg.Pool,
    name: str,
    int_type: str,
    config: dict[str, Any],
    secret: str | None,
    actor: dict,
) -> dict[str, Any]:
    adapter = get_adapter(int_type)
    try:
        adapter.validate_config(config)
    except ValueError as exc:
        raise IntegrationError(str(exc))

    integration_id = str(uuid.uuid4())
    await store.insert_integration(pool, integration_id, name, int_type, config, secret)
    await store.audit(pool, actor["sub"], actor["email"], "integration.create", "integration", integration_id, {"name": name, "type": int_type})
    await store.syslog(pool, "INFO", "integration_service", f"created {int_type}: {name}")
    return await store.get_integration(pool, integration_id) or {}


async def test(pool: asyncpg.Pool, integration_id: str) -> dict[str, Any]:
    row = await store.get_integration(pool, integration_id)
    if not row:
        raise IntegrationError(f"Integration not found: {integration_id}")
    adapter = get_adapter(row["type"])
    result  = await adapter.test_connection(row["config"] or {}, row.get("secret"))
    await store.update_integration(pool, integration_id, {
        "status":     "active" if result["ok"] else "error",
        "sync_error": None if result["ok"] else result.get("message"),
    })
    return result


async def ingest(
    pool: asyncpg.Pool,
    arq: Any,
    integration_id: str,
    payload: dict[str, Any],
) -> str | None:
    row = await store.get_integration(pool, integration_id)
    if not row:
        raise IntegrationError(f"Integration not found: {integration_id}")
    if row.get("status") != "active":
        raise IntegrationError(f"Integration {integration_id!r} is not active")

    adapter     = get_adapter(row["type"])
    ticket_data = adapter.parse_inbound(payload, row.get("secret"))

    if ticket_data is None:
        await store.record_integration_event(pool, integration_id, "inbound", "ignored")
        return None

    from services.ticket_service import create as create_ticket
    actor = {"sub": "system", "email": "system@autosupport.internal"}
    ticket = await create_ticket(pool, arq, ticket_data, actor)
    ticket_id = ticket["id"]

    await store.record_integration_event(pool, integration_id, "inbound", "ok", ticket_id=ticket_id)
    await store.update_integration(pool, integration_id, {"last_sync_at": datetime.now(UTC)})
    logger.info("integration.ingested", integration_id=integration_id, ticket_id=ticket_id)
    return ticket_id


async def delete(pool: asyncpg.Pool, integration_id: str, actor: dict) -> None:
    if not await store.get_integration(pool, integration_id):
        raise IntegrationError(f"Integration not found: {integration_id}")
    await store.delete_integration(pool, integration_id)
    await store.audit(pool, actor["sub"], actor["email"], "integration.delete", "integration", integration_id)
