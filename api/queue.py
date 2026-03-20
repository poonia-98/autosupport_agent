from fastapi import APIRouter, Depends, Query, Request

from core.security import require_auth, require_operator
from db import store

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.get("")
async def list_jobs(
    request:  Request,
    limit:    int           = Query(default=50, ge=1, le=200),
    status:   str | None    = Query(default=None),
    identity: dict          = Depends(require_auth),
):
    pool = request.app.state.pool
    return await store.list_job_log(pool, limit=limit, status=status)


@router.post("/{ticket_id}/retry")
async def retry_job(
    ticket_id: str,
    request:   Request,
    identity:  dict = Depends(require_operator),
):
    """Re-enqueue classification for a ticket whose job failed."""
    import uuid

    from fastapi import HTTPException
    from fastapi import status as http_status
    pool = request.app.state.pool
    arq  = request.app.state.arq

    ticket = await store.get_ticket(pool, ticket_id)
    if not ticket:
        raise HTTPException(http_status.HTTP_404_NOT_FOUND, detail="Ticket not found")

    correlation_id = str(uuid.uuid4())
    job = await arq.enqueue_job(
        "classify_ticket",
        ticket_id      = ticket_id,
        correlation_id = correlation_id,
    )
    job_id = job.job_id if job else ticket_id
    await store.upsert_job_status(pool, job_id, ticket_id, "enqueued")
    return {"job_id": job_id, "ticket_id": ticket_id, "status": "enqueued"}
