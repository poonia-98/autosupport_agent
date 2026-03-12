import json
import time
from datetime import datetime, timezone
from typing import Any, Optional, Union

import asyncpg

# Type alias — both Pool and Connection support fetchrow/execute
Conn = Union[asyncpg.Pool, asyncpg.Connection]


# ── helpers ───────────────────────────────────────────────────────────────────

def _to_dict(row: asyncpg.Record | None) -> Optional[dict[str, Any]]:
    if row is None:
        return None
    d = dict(row)
    # convert datetime → unix float for consistent API response format
    for k, v in d.items():
        if isinstance(v, datetime):
            d[k] = v.timestamp()
    return d


def _rows(rows) -> list[dict[str, Any]]:
    return [_to_dict(r) for r in rows]  # type: ignore[misc]


# ── users ─────────────────────────────────────────────────────────────────────

async def insert_user(conn: Conn, user_id: str, email: str, name: str, role: str, password_hash: str) -> None:
    await conn.execute(
        "INSERT INTO users(id, email, name, role, password_hash) VALUES($1,$2,$3,$4,$5)",
        user_id, email, name, role, password_hash,
    )


async def get_user_by_email(conn: Conn, email: str) -> Optional[dict[str, Any]]:
    row = await conn.fetchrow("SELECT * FROM users WHERE email=$1", email)
    return _to_dict(row)


async def get_user_by_id(conn: Conn, user_id: str) -> Optional[dict[str, Any]]:
    row = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
    return _to_dict(row)


async def list_users(conn: Conn) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT id,email,name,role,active,created_at FROM users ORDER BY created_at"
    )
    return _rows(rows)


async def update_user(conn: Conn, user_id: str, updates: dict[str, Any]) -> None:
    _ALLOWED = {"name", "role", "active", "password_hash", "updated_at"}
    safe = {k: v for k, v in updates.items() if k in _ALLOWED}
    if not safe:
        return
    safe["updated_at"] = datetime.now(timezone.utc)
    cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(safe))
    await conn.execute(
        f"UPDATE users SET {cols} WHERE id=$1",
        user_id, *safe.values(),
    )


async def increment_token_version(conn: Conn, user_id: str) -> None:
    await conn.execute(
        "UPDATE users SET token_version=token_version+1, updated_at=NOW() WHERE id=$1",
        user_id,
    )


async def user_exists(conn: Conn) -> bool:
    count = await conn.fetchval("SELECT COUNT(*) FROM users")
    return (count or 0) > 0


# ── tickets ───────────────────────────────────────────────────────────────────

async def insert_ticket(conn: Conn, ticket_id: str, data: dict[str, Any]) -> None:
    await conn.execute(
        """
        INSERT INTO tickets
          (id, title, description, user_id, priority, category, status,
           response_sla_breached, source, integration_ref, idempotency_key)
        VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11)
        """,
        ticket_id,
        data["title"],
        data.get("description", ""),
        data.get("user_id"),
        data.get("priority", "medium"),
        data.get("category", "general"),
        data.get("status", "open"),
        bool(data.get("response_sla_breached", False)),
        data.get("source", "api"),
        data.get("integration_ref"),
        data.get("idempotency_key"),
    )


async def get_ticket(conn: Conn, ticket_id: str) -> Optional[dict[str, Any]]:
    row = await conn.fetchrow("SELECT * FROM tickets WHERE id=$1", ticket_id)
    return _to_dict(row)


async def get_ticket_by_idempotency_key(conn: Conn, key: str) -> Optional[dict[str, Any]]:
    row = await conn.fetchrow("SELECT * FROM tickets WHERE idempotency_key=$1", key)
    return _to_dict(row)


async def update_ticket(conn: Conn, ticket_id: str, updates: dict[str, Any]) -> None:
    _ALLOWED = {
        "title", "description", "priority", "category", "status",
        "assigned_team", "assigned_to", "suggested_response",
        "response_sla_breached", "first_response_at", "resolved_at",
    }
    safe = {k: v for k, v in updates.items() if k in _ALLOWED}
    if not safe:
        return
    safe["updated_at"] = datetime.now(timezone.utc)
    cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(safe))
    await conn.execute(
        f"UPDATE tickets SET {cols} WHERE id=$1",
        ticket_id, *safe.values(),
    )


async def transition_ticket_status(
    conn: asyncpg.Connection,
    ticket_id: str,
    from_status: str,
    to_status: str,
) -> bool:
    """Atomic CAS-style status update. Returns False if ticket was not in expected state."""
    result = await conn.execute(
        "UPDATE tickets SET status=$1, updated_at=NOW() WHERE id=$2 AND status=$3",
        to_status, ticket_id, from_status,
    )
    return result == "UPDATE 1"


async def delete_ticket(conn: Conn, ticket_id: str) -> None:
    # soft-delete via status; physical delete kept for admin purge only
    await conn.execute(
        "UPDATE tickets SET status='closed', updated_at=NOW() WHERE id=$1",
        ticket_id,
    )


async def get_tickets_page(
    conn: Conn,
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    category: Optional[str] = None,
    search: Optional[str] = None,
) -> tuple[list[dict[str, Any]], int]:
    """Items + total in one round-trip via window function."""
    clauses: list[str] = []
    params: list[Any] = []
    idx = 1

    if status:
        clauses.append(f"status=${idx}"); params.append(status); idx += 1
    if priority:
        clauses.append(f"priority=${idx}"); params.append(priority); idx += 1
    if category:
        clauses.append(f"category=${idx}"); params.append(category); idx += 1
    if search:
        clauses.append(f"search_vector @@ plainto_tsquery('english', ${idx})")
        params.append(search); idx += 1

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = await conn.fetch(
        f"""
        SELECT *, COUNT(*) OVER() AS _total
        FROM tickets
        {where}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx+1}
        """,
        *params, min(limit, 200), offset,
    )

    if not rows:
        return [], 0

    total = rows[0]["_total"]
    items = []
    for r in rows:
        d = _to_dict(r)
        d.pop("_total", None)
        items.append(d)
    return items, total


async def bulk_close_tickets(conn: asyncpg.Connection, ticket_ids: list[str]) -> tuple[int, list[str]]:
    """Single transaction — returns (closed_count, not_found_ids)."""
    async with conn.transaction():
        result = await conn.execute(
            """
            UPDATE tickets
            SET status='closed', updated_at=NOW()
            WHERE id = ANY($1::text[])
              AND status NOT IN ('resolved','closed')
            """,
            ticket_ids,
        )
        closed = int(result.split()[-1])

        existing = await conn.fetch(
            "SELECT id FROM tickets WHERE id = ANY($1::text[])", ticket_ids
        )
        existing_ids = {r["id"] for r in existing}
        missing = [tid for tid in ticket_ids if tid not in existing_ids]

    return closed, missing


# ── task queue ────────────────────────────────────────────────────────────────
# The primary queue is ARQ/Redis. This table tracks job status for visibility
# and allows manual retry from the dashboard.

async def upsert_job_status(
    conn: Conn,
    job_id: str,
    ticket_id: str,
    status: str,
    error: Optional[str] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO job_log(job_id, ticket_id, status, error, updated_at)
        VALUES ($1,$2,$3,$4,NOW())
        ON CONFLICT (job_id) DO UPDATE
          SET status=$3, error=$4, updated_at=NOW()
        """,
        job_id, ticket_id, status, error,
    )


async def list_job_log(
    conn: Conn,
    limit: int = 50,
    status: Optional[str] = None,
) -> list[dict[str, Any]]:
    where = "WHERE jl.status=$1" if status else ""
    params: list[Any] = [status, limit] if status else [limit]
    rows = await conn.fetch(
        f"""
        SELECT jl.*, t.title, t.priority
        FROM job_log jl
        LEFT JOIN tickets t ON t.id=jl.ticket_id
        {where}
        ORDER BY jl.updated_at DESC LIMIT ${2 if status else 1}
        """,
        *params,
    )
    return _rows(rows)


# ── agent events ──────────────────────────────────────────────────────────────

async def record_agent_event(
    conn: Conn, ticket_id: str, agent: str, result: dict[str, Any], duration_ms: int
) -> None:
    await conn.execute(
        "INSERT INTO agent_events(ticket_id, agent, result, duration_ms) VALUES($1,$2,$3,$4)",
        ticket_id, agent, json.dumps(result), duration_ms,
    )


async def get_recent_events(conn: Conn, limit: int = 50) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT ae.ticket_id, ae.agent, ae.result, ae.duration_ms, ae.ts,
               t.priority, t.category, t.title
        FROM agent_events ae
        LEFT JOIN tickets t ON t.id=ae.ticket_id
        ORDER BY ae.ts DESC LIMIT $1
        """,
        limit,
    )
    events = []
    for r in rows:
        d = _to_dict(r)
        if d and isinstance(d.get("result"), str):
            try:
                d["result"] = json.loads(d["result"])
            except (ValueError, TypeError):
                pass
        events.append(d)
    return events


async def get_agent_stats(conn: Conn) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT agent,
               COUNT(*) AS total_runs,
               ROUND(AVG(duration_ms)::numeric, 1) AS avg_ms,
               MAX(ts) AS last_run_ts
        FROM agent_events
        WHERE ts > NOW() - INTERVAL '24 hours'
        GROUP BY agent
        ORDER BY agent
        """
    )
    return _rows(rows)


# ── integrations ──────────────────────────────────────────────────────────────

async def insert_integration(
    conn: Conn, integration_id: str, name: str, int_type: str,
    config: dict, secret: Optional[str] = None,
) -> None:
    await conn.execute(
        "INSERT INTO integrations(id,name,type,config,secret) VALUES($1,$2,$3,$4,$5)",
        integration_id, name, int_type, json.dumps(config), secret,
    )


async def get_integration(conn: Conn, integration_id: str) -> Optional[dict[str, Any]]:
    row = await conn.fetchrow("SELECT * FROM integrations WHERE id=$1", integration_id)
    if not row:
        return None
    d = _to_dict(row)
    if d and isinstance(d.get("config"), str):
        try:
            d["config"] = json.loads(d["config"])
        except (ValueError, TypeError):
            pass
    return d


async def list_integrations(conn: Conn) -> list[dict[str, Any]]:
    rows = await conn.fetch("SELECT * FROM integrations ORDER BY created_at DESC")
    result = []
    for r in rows:
        d = _to_dict(r)
        if d:
            if isinstance(d.get("config"), str):
                try:
                    d["config"] = json.loads(d["config"])
                except (ValueError, TypeError):
                    pass
            d.pop("secret", None)
            result.append(d)
    return result


async def update_integration(conn: Conn, integration_id: str, updates: dict[str, Any]) -> None:
    _ALLOWED = {"name", "type", "config", "secret", "status", "last_sync_at", "sync_error", "event_count"}
    safe = {k: v for k, v in updates.items() if k in _ALLOWED}
    if not safe:
        return
    if "config" in safe and isinstance(safe["config"], dict):
        safe["config"] = json.dumps(safe["config"])
    safe["updated_at"] = datetime.now(timezone.utc)
    cols = ", ".join(f"{k}=${i+2}" for i, k in enumerate(safe))
    await conn.execute(
        f"UPDATE integrations SET {cols} WHERE id=$1",
        integration_id, *safe.values(),
    )


async def delete_integration(conn: Conn, integration_id: str) -> None:
    await conn.execute("DELETE FROM integrations WHERE id=$1", integration_id)


async def record_integration_event(
    conn: Conn,
    integration_id: str,
    direction: str,
    status: str,
    payload: Optional[dict] = None,
    ticket_id: Optional[str] = None,
    error: Optional[str] = None,
) -> None:
    payload_size = len(json.dumps(payload)) if payload else None
    async with (conn if isinstance(conn, asyncpg.Connection) else conn.acquire()) as c:
        if isinstance(conn, asyncpg.Pool):
            pass  # c is the acquired connection
        else:
            c = conn
        await c.execute(
            """
            INSERT INTO integration_events(integration_id, direction, status, payload_size, ticket_id, error)
            VALUES($1,$2,$3,$4,$5,$6)
            """,
            integration_id, direction, status, payload_size, ticket_id, error,
        )
        await c.execute(
            "UPDATE integrations SET event_count=event_count+1, updated_at=NOW() WHERE id=$1",
            integration_id,
        )


async def get_integration_events(conn: Conn, integration_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT ie.*, t.title AS ticket_title
        FROM integration_events ie
        LEFT JOIN tickets t ON t.id=ie.ticket_id
        WHERE ie.integration_id=$1
        ORDER BY ie.ts DESC LIMIT $2
        """,
        integration_id, limit,
    )
    return _rows(rows)


# ── audit + system log ────────────────────────────────────────────────────────

async def audit(
    conn: Conn,
    user_id: str,
    user_email: str,
    action: str,
    resource_type: str,
    resource_id: Optional[str] = None,
    meta: Optional[dict] = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO audit_log(user_id, user_email, action, resource_type, resource_id, meta)
        VALUES($1,$2,$3,$4,$5,$6)
        """,
        user_id, user_email, action, resource_type, resource_id,
        json.dumps(meta) if meta else None,
    )


async def get_audit_log(conn: Conn, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT * FROM audit_log ORDER BY ts DESC LIMIT $1 OFFSET $2",
        limit, offset,
    )
    result = []
    for r in rows:
        d = _to_dict(r)
        if d and isinstance(d.get("meta"), str):
            try:
                d["meta"] = json.loads(d["meta"])
            except (ValueError, TypeError):
                pass
        result.append(d)
    return result


async def syslog(conn: Conn, level: str, source: str, message: str) -> None:
    await conn.execute(
        "INSERT INTO system_log(level, source, message) VALUES($1,$2,$3)",
        level, source, message[:500],
    )


async def get_log_tail(conn: Conn, limit: int = 60, level: Optional[str] = None) -> list[dict[str, Any]]:
    if level:
        rows = await conn.fetch(
            "SELECT * FROM system_log WHERE level=$1 ORDER BY ts DESC LIMIT $2",
            level, limit,
        )
    else:
        rows = await conn.fetch(
            "SELECT * FROM system_log ORDER BY ts DESC LIMIT $1", limit
        )
    return _rows(rows)


async def prune_logs(conn: Conn, system_log_days: int = 7, audit_log_days: int = 90) -> None:
    await conn.execute(
        "DELETE FROM system_log WHERE ts < NOW() - ($1 || ' days')::interval",
        str(system_log_days),
    )
    await conn.execute(
        "DELETE FROM audit_log WHERE ts < NOW() - ($1 || ' days')::interval",
        str(audit_log_days),
    )


# ── analytics ─────────────────────────────────────────────────────────────────

async def get_analytics(conn: Conn) -> dict[str, Any]:
    total       = await conn.fetchval("SELECT COUNT(*) FROM tickets")
    open_count  = await conn.fetchval(
        "SELECT COUNT(*) FROM tickets WHERE status NOT IN ('resolved','closed')"
    )
    resolved_today = await conn.fetchval(
        "SELECT COUNT(*) FROM tickets WHERE status='resolved' AND resolved_at >= CURRENT_DATE"
    )
    pending     = await conn.fetchval("SELECT COUNT(*) FROM job_log WHERE status='enqueued'")
    failed      = await conn.fetchval("SELECT COUNT(*) FROM job_log WHERE status='failed'")
    sla_at_risk = await conn.fetchval(
        "SELECT COUNT(*) FROM tickets WHERE response_sla_breached=true AND status NOT IN ('resolved','closed')"
    )
    by_priority = {r["priority"]: r["cnt"] for r in await conn.fetch(
        "SELECT COALESCE(priority,'unknown') AS priority, COUNT(*) AS cnt FROM tickets GROUP BY priority"
    )}
    by_category = {r["category"]: r["cnt"] for r in await conn.fetch(
        "SELECT COALESCE(category,'unknown') AS category, COUNT(*) AS cnt FROM tickets GROUP BY category"
    )}
    by_status   = {r["status"]: r["cnt"] for r in await conn.fetch(
        "SELECT COALESCE(status,'unknown') AS status, COUNT(*) AS cnt FROM tickets GROUP BY status"
    )}
    return {
        "total_tickets":   total or 0,
        "open_tickets":    open_count or 0,
        "resolved_today":  resolved_today or 0,
        "failed_jobs":     failed or 0,
        "pending_jobs":    pending or 0,
        "sla_at_risk":     sla_at_risk or 0,
        "by_priority":     by_priority,
        "by_category":     by_category,
        "by_status":       by_status,
    }


async def get_time_series(conn: Conn, days: int = 7) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        """
        SELECT DATE(created_at) AS day,
               COUNT(*) AS created,
               SUM(CASE WHEN status='resolved' THEN 1 ELSE 0 END) AS resolved
        FROM tickets
        WHERE created_at >= NOW() - ($1 || ' days')::interval
        GROUP BY day ORDER BY day
        """,
        str(days),
    )
    return [{"date": str(r["day"]), "created": r["created"], "resolved": r["resolved"]} for r in rows]


async def get_sla_compliance(conn: Conn, days: int = 30) -> dict[str, Any]:
    row = await conn.fetchrow(
        """
        SELECT
          COUNT(*)                                      AS total,
          SUM(CASE WHEN response_sla_breached THEN 1 ELSE 0 END) AS breached,
          ROUND(AVG(
            EXTRACT(EPOCH FROM (resolved_at - created_at))
          )::numeric, 0)                               AS avg_resolution_secs
        FROM tickets
        WHERE created_at >= NOW() - ($1 || ' days')::interval
        """,
        str(days),
    )
    total    = row["total"] or 0
    breached = row["breached"] or 0
    compliant = total - breached
    rate = round(compliant / total * 100, 1) if total > 0 else 100.0
    return {
        "total": total,
        "compliant": compliant,
        "breached": breached,
        "compliance_rate": rate,
        "avg_resolution_seconds": int(row["avg_resolution_secs"]) if row["avg_resolution_secs"] else None,
    }


# ── engineer round-robin (in-process state, acceptable for single-node) ───────

_TEAM_ROSTER: dict[str, list[str]] = {
    "sre_team":      ["alice.chen", "bob.okafor"],
    "backend_team":  ["carol.smith", "dan.patel"],
    "billing_team":  ["frank.li", "grace.kim"],
    "product_team":  ["iris.costa"],
    "tier1_support": ["jack.mueller", "karen.santos", "liam.nguyen"],
}

_TEAM_SKILLS: dict[str, list[str]] = {
    "sre_team":      ["infrastructure", "incidents", "kubernetes"],
    "backend_team":  ["api", "database", "performance", "bugs"],
    "billing_team":  ["payments", "subscriptions", "refunds"],
    "product_team":  ["features", "roadmap"],
    "tier1_support": ["general", "documentation"],
}

_round_robin: dict[str, int] = {}


def get_available_engineer(skills: list[str]) -> Optional[str]:
    for team, team_skills in _TEAM_SKILLS.items():
        if any(s in team_skills for s in skills):
            members = _TEAM_ROSTER.get(team, [])
            if not members:
                continue
            idx = _round_robin.get(team, 0) % len(members)
            _round_robin[team] = idx + 1
            return members[idx]
    return None
