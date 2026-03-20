from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from core.exceptions import IntegrationError
from core.security import require_auth, require_operator
from db import store
from integrations import supported_types
from services import integration_service

router = APIRouter(prefix="/api/integrations", tags=["integrations"])


class CreateIntegrationRequest(BaseModel):
    name: str
    type: str
    config: dict[str, Any] = {}
    secret: str | None = None


@router.get("")
async def list_integrations(request: Request, identity: dict = Depends(require_auth)):
    return await store.list_integrations(request.app.state.pool)


@router.get("/types")
async def get_supported_types(identity: dict = Depends(require_auth)):
    return {"types": supported_types()}


@router.post("", status_code=status.HTTP_200_OK)
async def create_integration(
    body: CreateIntegrationRequest,
    request: Request,
    identity: dict = Depends(require_operator),
):
    try:
        return await integration_service.create(request.app.state.pool, body.name, body.type, body.config, body.secret, identity)
    except IntegrationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))


@router.get("/{integration_id}")
async def get_integration(
    integration_id: str,
    request: Request,
    identity: dict = Depends(require_auth),
):
    row = await store.get_integration(request.app.state.pool, integration_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Integration not found")
    row.pop("secret", None)
    return row


@router.post("/{integration_id}/test")
async def test_integration(
    integration_id: str,
    request: Request,
    identity: dict = Depends(require_operator),
):
    try:
        return await integration_service.test(request.app.state.pool, integration_id)
    except IntegrationError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))


@router.post("/{integration_id}/ingest", status_code=status.HTTP_200_OK)
async def ingest(
    integration_id: str,
    payload: dict[str, Any],
    request: Request,
):
    """Inbound webhook — no auth required, protected by HMAC via adapter."""
    try:
        ticket_id = await integration_service.ingest(request.app.state.pool, request.app.state.arq, integration_id, payload)
    except IntegrationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"ticket_id": ticket_id, "accepted": True}


@router.get("/{integration_id}/events")
async def integration_events(
    integration_id: str,
    request: Request,
    identity: dict = Depends(require_auth),
):
    return await store.get_integration_events(request.app.state.pool, integration_id)


@router.delete("/{integration_id}", status_code=status.HTTP_200_OK)
async def delete_integration(
    integration_id: str,
    request: Request,
    identity: dict = Depends(require_operator),
):
    try:
        await integration_service.delete(request.app.state.pool, integration_id, identity)
    except IntegrationError as exc:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail=str(exc))
    return {"ok": True}

