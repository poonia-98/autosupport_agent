from typing import Any

from fastapi import APIRouter, Depends, Request

from core.security import require_auth
from db import store

router = APIRouter(prefix="/api/agents", tags=["agents"])

_DESCRIPTIONS: dict[str, str] = {
    "ticket_classifier":   "Classifies intent/category via keyword routing + optional LLM",
    "priority_predictor":  "Weighted priority score from 6 signals",
    "escalation_detector": "Threshold-based escalation from 6 independent signals",
    "response_suggester":  "Template response + action list from intent+escalation",
    "auto_router":         "Maps intent+priority to team and engineer",
}


@router.get("")
async def get_agent_stats(
    request:  Request,
    identity: dict = Depends(require_auth),
) -> list[dict[str, Any]]:
    pool   = request.app.state.pool
    stats  = await store.get_agent_stats(pool)
    by_name = {s["agent"]: s for s in stats}
    return [
        {
            "agent":       name,
            "total_runs":  by_name.get(name, {}).get("total_runs", 0),
            "avg_ms":      by_name.get(name, {}).get("avg_ms"),
            "last_run_ts": by_name.get(name, {}).get("last_run_ts"),
            "description": desc,
        }
        for name, desc in _DESCRIPTIONS.items()
    ]


@router.get("/events")
async def recent_events(
    request:  Request,
    identity: dict = Depends(require_auth),
) -> list[dict[str, Any]]:
    pool = request.app.state.pool
    return await store.get_recent_events(pool, limit=50)
