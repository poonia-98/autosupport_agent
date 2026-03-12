from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import Response

from core.config import get_settings
from core.metrics import metrics_response
from core.security import require_admin, require_auth
from db import store

router = APIRouter(tags=["system"])


@router.get("/health")
async def health(request: Request):
    try:
        pool = request.app.state.pool
        await pool.fetchval("SELECT 1")
        db_ok = True
    except Exception:
        db_ok = False

    try:
        redis = request.app.state.redis
        await redis.ping()
        redis_ok = True
    except Exception:
        redis_ok = False

    return {
        "status":   "ok" if (db_ok and redis_ok) else "degraded",
        "db":       "ok" if db_ok else "error",
        "redis":    "ok" if redis_ok else "error",
        "version":  get_settings().version,
    }


@router.get("/metrics")
async def prometheus_metrics():
    data, content_type = metrics_response()
    if data is None:
        return {"error": "prometheus-client not installed"}
    return Response(content=data, media_type=content_type)


@router.get("/api/audit")
async def audit_log(
    request:  Request,
    limit:    int  = Query(default=100, ge=1, le=500),
    offset:   int  = Query(default=0, ge=0),
    identity: dict = Depends(require_admin),
):
    pool = request.app.state.pool
    return await store.get_audit_log(pool, limit=limit, offset=offset)


@router.get("/api/system/log")
async def system_log(
    request:  Request,
    limit:    int          = Query(default=60, ge=1, le=200),
    level:    str | None   = Query(default=None),
    identity: dict         = Depends(require_auth),
):
    pool = request.app.state.pool
    return await store.get_log_tail(pool, limit=limit, level=level)
