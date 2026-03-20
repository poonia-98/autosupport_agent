from fastapi import APIRouter, Depends, Query, Request

from core.security import require_auth
from db import store
from services.sla_service import compute_metrics as sla_metrics

router = APIRouter(prefix="/api/analytics", tags=["analytics"])


@router.get("")
async def get_analytics(
    request: Request,
    identity: dict = Depends(require_auth),
):
    pool = request.app.state.pool
    return await store.get_analytics(pool)


@router.get("/time-series")
async def time_series(
    request: Request,
    days: int = Query(default=7, ge=1, le=90),
    identity: dict = Depends(require_auth),
):
    pool = request.app.state.pool
    return await store.get_time_series(pool, days)


@router.get("/sla")
async def sla_compliance(
    request: Request,
    days: int = Query(default=30, ge=1, le=365),
    identity: dict = Depends(require_auth),
):
    pool = request.app.state.pool
    return await store.get_sla_compliance(pool, days)


@router.get("/ops")
async def operational_intelligence(
    request: Request,
    hours: int = Query(default=24, ge=6, le=168),
    agent_window_minutes: int = Query(default=60, ge=15, le=1440),
    identity: dict = Depends(require_auth),
):
    pool = request.app.state.pool
    return await store.get_operational_insights(pool, hours=hours, agent_window_minutes=agent_window_minutes)


@router.get("/sla/{ticket_id}")
async def ticket_sla(
    ticket_id: str,
    request: Request,
    identity: dict = Depends(require_auth),
):
    from fastapi import HTTPException, status

    pool = request.app.state.pool
    ticket = await store.get_ticket(pool, ticket_id)
    if not ticket:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return await sla_metrics(ticket)

