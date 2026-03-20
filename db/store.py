import json
import time
from datetime import datetime, timezone
from typing import Any

import asyncpg

# Type alias — both Pool and Connection support fetchrow/execute
Conn = asyncpg.Pool | asyncpg.Connection


# ── helpers ───────────────────────────────────────────────────────────────────


def _to_dict(row: asyncpg.Record | None) -> dict[str, Any] | None:
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


def _normalize_db_value(value: Any) -> Any:
    if isinstance(value, str) and value.upper() == "NOW()":
        return datetime.now(timezone.utc)
    return value


# ── users ─────────────────────────────────────────────────────────────────────


async def insert_user(conn: Conn, user_id: str, email: str, name: str, role: str, password_hash: str) -> None:
    await conn.execute(
        "INSERT INTO users(id, email, name, role, password_hash) VALUES($1,$2,$3,$4,$5)",
        user_id,
        email,
        name,
        role,
        password_hash,
    )


async def get_user_by_email(conn: Conn, email: str) -> dict[str, Any] | None:
    row = await conn.fetchrow("SELECT * FROM users WHERE email=$1", email)
    return _to_dict(row)


async def get_user_by_id(conn: Conn, user_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow("SELECT * FROM users WHERE id=$1", user_id)
    return _to_dict(row)


async def list_users(conn: Conn) -> list[dict[str, Any]]:
    rows = await conn.fetch("SELECT id,email,name,role,active,created_at FROM users ORDER BY created_at")
    return _rows(rows)


async def update_user(conn: Conn, user_id: str, updates: dict[str, Any]) -> None:
    _ALLOWED = {"name", "role", "active", "password_hash", "updated_at"}
    safe = {k: _normalize_db_value(v) for k, v in updates.items() if k in _ALLOWED}
    if not safe:
        return
    safe["updated_at"] = datetime.now(timezone.utc)
    cols = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(safe))
    await conn.execute(
        f"UPDATE users SET {cols} WHERE id=$1",
        user_id,
        *safe.values(),
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


async def get_ticket(conn: Conn, ticket_id: str) -> dict[str, Any] | None:
    row = await conn.fetchrow("SELECT * FROM tickets WHERE id=$1", ticket_id)
    return _to_dict(row)


async def get_ticket_by_idempotency_key(conn: Conn, key: str) -> dict[str, Any] | None:
    row = await conn.fetchrow("SELECT * FROM tickets WHERE idempotency_key=$1", key)
    return _to_dict(row)


async def update_ticket(conn: Conn, ticket_id: str, updates: dict[str, Any]) -> None:
    _ALLOWED = {
        "title",
        "description",
        "priority",
        "category",
        "status",
        "assigned_team",
        "assigned_to",
        "suggested_response",
        "response_sla_breached",
        "first_response_at",
        "resolved_at",
    }
    safe = {k: _normalize_db_value(v) for k, v in updates.items() if k in _ALLOWED}
    if not safe:
        return
    safe["updated_at"] = datetime.now(timezone.utc)
    cols = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(safe))
    await conn.execute(
        f"UPDATE tickets SET {cols} WHERE id=$1",
        ticket_id,
        *safe.values(),
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
        to_status,
        ticket_id,
        from_status,
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
    status: str | None = None,
    priority: str | None = None,
    category: str | None = None,
    search: str | None = None,
) -> tuple[list[dict[str, Any]], int]:
    """Items + total in one round-trip via window function."""
    clauses: list[str] = []
    params: list[Any] = []
    idx = 1

    if status:
        clauses.append(f"status=${idx}")
        params.append(status)
        idx += 1
    if priority:
        clauses.append(f"priority=${idx}")
        params.append(priority)
        idx += 1
    if category:
        clauses.append(f"category=${idx}")
        params.append(category)
        idx += 1
    if search:
        clauses.append(f"search_vector @@ plainto_tsquery('english', ${idx})")
        params.append(search)
        idx += 1

    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    rows = await conn.fetch(
        f"""
        SELECT *, COUNT(*) OVER() AS _total
        FROM tickets
        {where}
        ORDER BY created_at DESC
        LIMIT ${idx} OFFSET ${idx + 1}
        """,
        *params,
        min(limit, 200),
        offset,
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

        existing = await conn.fetch("SELECT id FROM tickets WHERE id = ANY($1::text[])", ticket_ids)
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
    error: str | None = None,
) -> None:
    attempts = 1 if status == "running" else 0
    await conn.execute(
        """
        INSERT INTO job_log(job_id, ticket_id, status, error, attempts, updated_at)
        VALUES ($1,$2,$3,$4,$5,NOW())
        ON CONFLICT (job_id) DO UPDATE
          SET status=$3,
              error=$4,
              attempts=CASE
                WHEN $3='running' THEN job_log.attempts + 1
                ELSE job_log.attempts
              END,
              updated_at=NOW()
        """,
        job_id,
        ticket_id,
        status,
        error,
        attempts,
    )


async def list_job_log(
    conn: Conn,
    limit: int = 50,
    status: str | None = None,
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


async def record_agent_event(conn: Conn, ticket_id: str, agent: str, result: dict[str, Any], duration_ms: int) -> None:
    normalized_duration = max(int(duration_ms or 0), 1)
    await conn.execute(
        "INSERT INTO agent_events(ticket_id, agent, result, duration_ms) VALUES($1,$2,$3,$4)",
        ticket_id,
        agent,
        json.dumps(result),
        normalized_duration,
    )


async def get_recent_events(
    conn: Conn,
    limit: int = 50,
    ticket_id: str | None = None,
) -> list[dict[str, Any]]:
    where = "WHERE ae.ticket_id=$1" if ticket_id else ""
    params: list[Any] = [ticket_id, limit] if ticket_id else [limit]
    rows = await conn.fetch(
        """
        SELECT ae.ticket_id, ae.agent, ae.result,
               CASE
                 WHEN ae.duration_ms IS NULL THEN NULL
                 ELSE GREATEST(ae.duration_ms, 1)
               END AS duration_ms,
               ae.ts,
               t.priority, t.category, t.title
        FROM agent_events ae
        LEFT JOIN tickets t ON t.id=ae.ticket_id
        """
        + f"{where}\n"
        + f"ORDER BY ae.ts DESC LIMIT ${2 if ticket_id else 1}",
        *params,
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
               ROUND(
                 AVG(
                   CASE
                     WHEN duration_ms IS NULL THEN NULL
                     ELSE GREATEST(duration_ms, 1)
                   END
                 )::numeric,
                 1
               ) AS avg_ms,
               MAX(ts) AS last_run_ts
        FROM agent_events
        WHERE ts > NOW() - INTERVAL '24 hours'
        GROUP BY agent
        ORDER BY agent
        """
    )
    return _rows(rows)


async def get_operational_insights(
    conn: Conn,
    hours: int = 24,
    agent_window_minutes: int = 60,
) -> dict[str, Any]:
    open_count = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE status NOT IN ('resolved','closed')") or 0

    queue_row = await conn.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (WHERE status='enqueued') AS enqueued,
          COUNT(*) FILTER (WHERE status='running') AS running,
          COUNT(*) FILTER (WHERE status='failed') AS failed,
          COUNT(*) FILTER (WHERE status='done') AS done,
          COALESCE(SUM(GREATEST(attempts - 1, 0)), 0) AS retries
        FROM job_log
        """
    )

    ops_row = await conn.fetchrow(
        """
        SELECT
          COUNT(*) FILTER (WHERE created_at >= NOW() - ($1 || ' hours')::interval) AS created_in_window,
          COUNT(*) FILTER (WHERE resolved_at >= NOW() - ($1 || ' hours')::interval) AS resolved_in_window,
          COUNT(*) FILTER (
            WHERE created_at >= NOW() - ($1 || ' hours')::interval
              AND assigned_team IS NOT NULL
              AND status <> 'escalated'
          ) AS automated_in_window,
          COUNT(*) FILTER (
            WHERE created_at >= NOW() - ($1 || ' hours')::interval
              AND status = 'escalated'
          ) AS escalated_in_window,
          COUNT(*) FILTER (
            WHERE status NOT IN ('resolved','closed')
              AND response_sla_breached = TRUE
          ) AS sla_risk_open
        FROM tickets
        """,
        str(hours),
    )

    throughput_rows = await conn.fetch(
        """
        WITH series AS (
          SELECT generate_series(
            date_trunc('hour', NOW() - ($1 || ' hours')::interval),
            date_trunc('hour', NOW()),
            interval '1 hour'
          ) AS bucket
        ),
        created AS (
          SELECT date_trunc('hour', created_at) AS bucket, COUNT(*) AS count
          FROM tickets
          WHERE created_at >= NOW() - ($1 || ' hours')::interval
          GROUP BY 1
        ),
        resolved AS (
          SELECT date_trunc('hour', resolved_at) AS bucket, COUNT(*) AS count
          FROM tickets
          WHERE resolved_at IS NOT NULL
            AND resolved_at >= NOW() - ($1 || ' hours')::interval
          GROUP BY 1
        ),
        processed AS (
          SELECT date_trunc('hour', updated_at) AS bucket, COUNT(*) AS count
          FROM job_log
          WHERE status='done'
            AND updated_at >= NOW() - ($1 || ' hours')::interval
          GROUP BY 1
        ),
        failed AS (
          SELECT date_trunc('hour', updated_at) AS bucket, COUNT(*) AS count
          FROM job_log
          WHERE status='failed'
            AND updated_at >= NOW() - ($1 || ' hours')::interval
          GROUP BY 1
        )
        SELECT
          s.bucket,
          COALESCE(c.count, 0) AS created,
          COALESCE(r.count, 0) AS resolved,
          COALESCE(p.count, 0) AS processed,
          COALESCE(f.count, 0) AS failed
        FROM series s
        LEFT JOIN created c ON c.bucket = s.bucket
        LEFT JOIN resolved r ON r.bucket = s.bucket
        LEFT JOIN processed p ON p.bucket = s.bucket
        LEFT JOIN failed f ON f.bucket = s.bucket
        ORDER BY s.bucket
        """,
        str(hours),
    )

    backlog_rows = await conn.fetch(
        """
        WITH series AS (
          SELECT generate_series(
            date_trunc('hour', NOW() - ($1 || ' hours')::interval),
            date_trunc('hour', NOW()),
            interval '1 hour'
          ) AS bucket
        )
        SELECT
          s.bucket,
          COUNT(t.id)::int AS backlog
        FROM series s
        LEFT JOIN tickets t
          ON t.created_at <= s.bucket
         AND (t.resolved_at IS NULL OR t.resolved_at > s.bucket)
        GROUP BY s.bucket
        ORDER BY s.bucket
        """,
        str(hours),
    )

    throughput: list[dict[str, Any]] = []
    backlog_points = [
        {
            "bucket": row["bucket"].timestamp(),
            "backlog": int(row["backlog"] or 0),
        }
        for row in backlog_rows
    ]
    backlog_points.append({"bucket": time.time(), "backlog": int(open_count)})

    for row in throughput_rows:
        throughput.append(
            {
                "bucket": row["bucket"].timestamp(),
                "created": int(row["created"] or 0),
                "resolved": int(row["resolved"] or 0),
                "processed": int(row["processed"] or 0),
                "failed": int(row["failed"] or 0),
            }
        )

    agent_rows = await conn.fetch(
        """
        SELECT
          agent,
          COUNT(*) AS total_runs,
          ROUND(AVG(GREATEST(duration_ms, 1))::numeric, 1)::float8 AS avg_ms,
          percentile_disc(0.95) WITHIN GROUP (ORDER BY GREATEST(duration_ms, 1))::int AS p95_ms,
          MAX(GREATEST(duration_ms, 1))::int AS max_ms,
          SUM(CASE WHEN COALESCE(result->>'status', 'ok')='failed' THEN 1 ELSE 0 END)::int AS failures,
          MAX(ts) AS last_run_ts
        FROM agent_events
        WHERE ts >= NOW() - ($1 || ' minutes')::interval
          AND duration_ms IS NOT NULL
        GROUP BY agent
        ORDER BY agent
        """,
        str(agent_window_minutes),
    )

    agent_performance = []
    for row in agent_rows:
        total_runs = int(row["total_runs"] or 0)
        failures = int(row["failures"] or 0)
        agent_performance.append(
            {
                "agent": row["agent"],
                "total_runs": total_runs,
                "avg_ms": float(row["avg_ms"] or 0.0),
                "p95_ms": int(row["p95_ms"] or 0),
                "max_ms": int(row["max_ms"] or 0),
                "failures": failures,
                "error_rate": round((failures / total_runs) * 100, 1) if total_runs else None,
                "executions_per_min": round(total_runs / max(agent_window_minutes, 1), 2),
                "last_run_ts": row["last_run_ts"].timestamp() if row["last_run_ts"] else None,
            }
        )

    slow_ticket_rows = await conn.fetch(
        """
        SELECT
          ae.ticket_id,
          t.title,
          t.priority,
          t.status,
          t.assigned_team,
          COUNT(*)::int AS stages,
          COALESCE(SUM(GREATEST(ae.duration_ms, 1)), 0)::int AS total_ms,
          COALESCE(MAX(GREATEST(ae.duration_ms, 1)), 0)::int AS slowest_stage_ms,
          MAX(ae.ts) AS last_event_ts
        FROM agent_events ae
        LEFT JOIN tickets t ON t.id = ae.ticket_id
        WHERE ae.ts >= NOW() - ($1 || ' hours')::interval
          AND ae.duration_ms IS NOT NULL
        GROUP BY ae.ticket_id, t.title, t.priority, t.status, t.assigned_team
        ORDER BY total_ms DESC, last_event_ts DESC
        LIMIT 8
        """,
        str(hours),
    )

    slow_tickets = [
        {
            "ticket_id": row["ticket_id"],
            "title": row["title"],
            "priority": row["priority"],
            "status": row["status"],
            "assigned_team": row["assigned_team"],
            "stages": int(row["stages"] or 0),
            "total_ms": int(row["total_ms"] or 0),
            "slowest_stage_ms": int(row["slowest_stage_ms"] or 0),
            "last_event_ts": row["last_event_ts"].timestamp() if row["last_event_ts"] else None,
        }
        for row in slow_ticket_rows
    ]

    heat_rows = await conn.fetch(
        """
        SELECT
          COALESCE(priority, 'unknown') AS priority,
          COUNT(*) FILTER (WHERE NOW() - created_at < INTERVAL '30 minutes')::int AS bucket_0_30m,
          COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '30 minutes' AND NOW() - created_at < INTERVAL '2 hours')::int AS bucket_30m_2h,
          COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '2 hours' AND NOW() - created_at < INTERVAL '8 hours')::int AS bucket_2h_8h,
          COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '8 hours' AND NOW() - created_at < INTERVAL '24 hours')::int AS bucket_8h_24h,
          COUNT(*) FILTER (WHERE NOW() - created_at >= INTERVAL '24 hours')::int AS bucket_24h_plus
        FROM tickets
        WHERE status NOT IN ('resolved','closed')
        GROUP BY priority
        """
    )

    priorities = ["critical", "high", "medium", "low"]
    heat_index = {row["priority"]: row for row in heat_rows}
    age_buckets = [
        {"key": "bucket_0_30m", "label": "<30m"},
        {"key": "bucket_30m_2h", "label": "30m-2h"},
        {"key": "bucket_2h_8h", "label": "2h-8h"},
        {"key": "bucket_8h_24h", "label": "8h-24h"},
        {"key": "bucket_24h_plus", "label": "24h+"},
    ]
    sla_heatmap = []
    for priority in priorities:
        row = heat_index.get(priority)
        cells = []
        for bucket in age_buckets:
            cells.append(
                {
                    "bucket": bucket["label"],
                    "count": int((row[bucket["key"]] if row else 0) or 0),
                }
            )
        sla_heatmap.append({"priority": priority, "cells": cells})

    last_six = throughput[-6:] if len(throughput) >= 6 else throughput
    avg_net = 0.0
    if last_six:
        avg_net = sum((point["resolved"] - point["created"]) for point in last_six) / len(last_six)
    forecast_hours = round(open_count / avg_net, 1) if avg_net > 0 else None

    automation = int(ops_row["automated_in_window"] or 0)
    escalated = int(ops_row["escalated_in_window"] or 0)
    automation_total = automation + escalated

    return {
        "generated_at": time.time(),
        "summary": {
            "open_tickets": int(open_count),
            "tickets_created_in_window": int(ops_row["created_in_window"] or 0),
            "tickets_resolved_in_window": int(ops_row["resolved_in_window"] or 0),
            "queue_depth": int(queue_row["enqueued"] or 0),
            "queue_running": int(queue_row["running"] or 0),
            "queue_failed": int(queue_row["failed"] or 0),
            "queue_done": int(queue_row["done"] or 0),
            "retry_count": int(queue_row["retries"] or 0),
            "sla_risk_open": int(ops_row["sla_risk_open"] or 0),
            "automation_success": automation,
            "human_escalations": escalated,
            "automation_ratio": round((automation / automation_total) * 100, 1) if automation_total else None,
            "forecast_hours_to_clear": forecast_hours,
        },
        "throughput": throughput,
        "backlog": backlog_points,
        "agent_performance": agent_performance,
        "slow_tickets": slow_tickets,
        "failing_agents": [row for row in agent_performance if (row.get("failures") or 0) > 0],
        "sla_heatmap": sla_heatmap,
        "age_buckets": [bucket["label"] for bucket in age_buckets],
    }


# ── integrations ──────────────────────────────────────────────────────────────


async def insert_integration(
    conn: Conn,
    integration_id: str,
    name: str,
    int_type: str,
    config: dict,
    secret: str | None = None,
) -> None:
    await conn.execute(
        "INSERT INTO integrations(id,name,type,config,secret) VALUES($1,$2,$3,$4,$5)",
        integration_id,
        name,
        int_type,
        json.dumps(config),
        secret,
    )


async def get_integration(conn: Conn, integration_id: str) -> dict[str, Any] | None:
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
    safe = {k: _normalize_db_value(v) for k, v in updates.items() if k in _ALLOWED}
    if not safe:
        return
    if "config" in safe and isinstance(safe["config"], dict):
        safe["config"] = json.dumps(safe["config"])
    safe["updated_at"] = datetime.now(timezone.utc)
    cols = ", ".join(f"{k}=${i + 2}" for i, k in enumerate(safe))
    await conn.execute(
        f"UPDATE integrations SET {cols} WHERE id=$1",
        integration_id,
        *safe.values(),
    )


async def delete_integration(conn: Conn, integration_id: str) -> None:
    await conn.execute("DELETE FROM integrations WHERE id=$1", integration_id)


async def record_integration_event(
    conn: Conn,
    integration_id: str,
    direction: str,
    status: str,
    payload: dict | None = None,
    ticket_id: str | None = None,
    error: str | None = None,
) -> None:
    payload_size = len(json.dumps(payload)) if payload else None
    if isinstance(conn, asyncpg.Connection):
        await conn.execute(
            """
            INSERT INTO integration_events(integration_id, direction, status, payload_size, ticket_id, error)
            VALUES($1,$2,$3,$4,$5,$6)
            """,
            integration_id,
            direction,
            status,
            payload_size,
            ticket_id,
            error,
        )
        await conn.execute(
            "UPDATE integrations SET event_count=event_count+1, updated_at=NOW() WHERE id=$1",
            integration_id,
        )
        return

    async with conn.acquire() as c:
        await c.execute(
            """
            INSERT INTO integration_events(integration_id, direction, status, payload_size, ticket_id, error)
            VALUES($1,$2,$3,$4,$5,$6)
            """,
            integration_id,
            direction,
            status,
            payload_size,
            ticket_id,
            error,
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
        integration_id,
        limit,
    )
    return _rows(rows)


# ── audit + system log ────────────────────────────────────────────────────────


async def audit(
    conn: Conn,
    user_id: str,
    user_email: str,
    action: str,
    resource_type: str,
    resource_id: str | None = None,
    meta: dict | None = None,
) -> None:
    await conn.execute(
        """
        INSERT INTO audit_log(user_id, user_email, action, resource_type, resource_id, meta)
        VALUES($1,$2,$3,$4,$5,$6)
        """,
        user_id,
        user_email,
        action,
        resource_type,
        resource_id,
        json.dumps(meta) if meta else None,
    )


async def get_audit_log(conn: Conn, limit: int = 100, offset: int = 0) -> list[dict[str, Any]]:
    rows = await conn.fetch(
        "SELECT * FROM audit_log ORDER BY ts DESC LIMIT $1 OFFSET $2",
        limit,
        offset,
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
        level,
        source,
        message[:500],
    )


async def get_log_tail(conn: Conn, limit: int = 60, level: str | None = None) -> list[dict[str, Any]]:
    if level:
        rows = await conn.fetch(
            "SELECT * FROM system_log WHERE level=$1 ORDER BY ts DESC LIMIT $2",
            level,
            limit,
        )
    else:
        rows = await conn.fetch("SELECT * FROM system_log ORDER BY ts DESC LIMIT $1", limit)
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
    total = await conn.fetchval("SELECT COUNT(*) FROM tickets")
    open_count = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE status NOT IN ('resolved','closed')")
    resolved_today = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE status='resolved' AND resolved_at >= CURRENT_DATE")
    pending = await conn.fetchval("SELECT COUNT(*) FROM job_log WHERE status='enqueued'")
    failed = await conn.fetchval("SELECT COUNT(*) FROM job_log WHERE status='failed'")
    sla_at_risk = await conn.fetchval("SELECT COUNT(*) FROM tickets WHERE response_sla_breached=true AND status NOT IN ('resolved','closed')")
    by_priority = {r["priority"]: r["cnt"] for r in await conn.fetch("SELECT COALESCE(priority,'unknown') AS priority, COUNT(*) AS cnt FROM tickets GROUP BY priority")}
    by_category = {r["category"]: r["cnt"] for r in await conn.fetch("SELECT COALESCE(category,'unknown') AS category, COUNT(*) AS cnt FROM tickets GROUP BY category")}
    by_status = {r["status"]: r["cnt"] for r in await conn.fetch("SELECT COALESCE(status,'unknown') AS status, COUNT(*) AS cnt FROM tickets GROUP BY status")}
    return {
        "total_tickets": total or 0,
        "open_tickets": open_count or 0,
        "resolved_today": resolved_today or 0,
        "failed_jobs": failed or 0,
        "pending_jobs": pending or 0,
        "sla_at_risk": sla_at_risk or 0,
        "by_priority": by_priority,
        "by_category": by_category,
        "by_status": by_status,
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
    total = row["total"] or 0
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
    "sre_team": ["alice.chen", "bob.okafor"],
    "backend_team": ["carol.smith", "dan.patel"],
    "billing_team": ["frank.li", "grace.kim"],
    "product_team": ["iris.costa"],
    "tier1_support": ["jack.mueller", "karen.santos", "liam.nguyen"],
}

_TEAM_SKILLS: dict[str, list[str]] = {
    "sre_team": ["infrastructure", "incidents", "kubernetes"],
    "backend_team": ["api", "database", "performance", "bugs"],
    "billing_team": ["payments", "subscriptions", "refunds"],
    "product_team": ["features", "roadmap"],
    "tier1_support": ["general", "documentation"],
}

_round_robin: dict[str, int] = {}


def get_available_engineer(skills: list[str]) -> str | None:
    for team, team_skills in _TEAM_SKILLS.items():
        if any(s in team_skills for s in skills):
            members = _TEAM_ROSTER.get(team, [])
            if not members:
                continue
            idx = _round_robin.get(team, 0) % len(members)
            _round_robin[team] = idx + 1
            return members[idx]
    return None

