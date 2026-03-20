
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status

from core.exceptions import InvalidStateTransition, TicketNotFound
from core.security import require_auth, require_operator
from models.ticket import BulkCloseRequest, CreateTicketRequest, UpdateTicketRequest
from services import ticket_service

router = APIRouter(prefix="/api/tickets", tags=["tickets"])


@router.post("", status_code=status.HTTP_200_OK)
async def create_ticket(
    body: CreateTicketRequest,
    request: Request,
    identity: dict = Depends(require_operator),
):
    pool = request.app.state.pool
    arq  = request.app.state.arq
    return await ticket_service.create(pool, arq, body.model_dump(exclude_none=True), identity)


@router.get("")
async def list_tickets(
    request:  Request,
    limit:    int           = Query(default=50, ge=1, le=200),
    offset:   int           = Query(default=0, ge=0),
    status:   str | None = Query(default=None),
    priority: str | None = Query(default=None),
    category: str | None = Query(default=None),
    search:   str | None = Query(default=None, max_length=200),
    identity: dict          = Depends(require_auth),
):
    pool = request.app.state.pool
    return await ticket_service.get_page(pool, limit=limit, offset=offset,
                                          status=status, priority=priority,
                                          category=category, search=search)


@router.get("/{ticket_id}")
async def get_ticket(
    ticket_id: str,
    request:   Request,
    identity:  dict = Depends(require_auth),
):
    from db import store
    pool   = request.app.state.pool
    ticket = await store.get_ticket(pool, ticket_id)
    if not ticket:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    return ticket


@router.patch("/{ticket_id}")
async def update_ticket(
    ticket_id: str,
    body:      UpdateTicketRequest,
    request:   Request,
    identity:  dict = Depends(require_operator),
):
    pool = request.app.state.pool
    try:
        return await ticket_service.update(pool, ticket_id, body.model_dump(exclude_none=True), identity)
    except TicketNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    except InvalidStateTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/{ticket_id}/resolve")
async def resolve_ticket(
    ticket_id: str,
    request:   Request,
    identity:  dict = Depends(require_operator),
):
    pool = request.app.state.pool
    try:
        return await ticket_service.resolve(pool, ticket_id, identity)
    except TicketNotFound:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Ticket not found")
    except InvalidStateTransition as exc:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=str(exc))


@router.post("/bulk-close")
async def bulk_close(
    body:     BulkCloseRequest,
    request:  Request,
    identity: dict = Depends(require_operator),
):
    pool = request.app.state.pool
    return await ticket_service.bulk_close(pool, body.ticket_ids, identity)
