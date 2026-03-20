from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.security import require_admin
from db import store
from models.user import CreateUserRequest, UpdateUserRequest
from services import user_service

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("")
async def list_users(request: Request, identity: dict = Depends(require_admin)):
    return await store.list_users(request.app.state.pool)


@router.post("", status_code=status.HTTP_200_OK)
async def create_user(
    body:     CreateUserRequest,
    request:  Request,
    identity: dict = Depends(require_admin),
):
    return await user_service.create_user(
        request.app.state.pool,
        body.email, body.name, body.role, body.password,
        identity,
    )


@router.get("/{user_id}")
async def get_user(user_id: str, request: Request, identity: dict = Depends(require_admin)):
    user = await store.get_user_by_id(request.app.state.pool, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")
    u = dict(user)
    u.pop("password_hash", None)
    u.pop("token_version", None)
    return u


@router.patch("/{user_id}")
async def update_user(
    user_id:  str,
    body:     UpdateUserRequest,
    request:  Request,
    identity: dict = Depends(require_admin),
):
    user = await store.get_user_by_id(request.app.state.pool, user_id)
    if not user:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="User not found")

    updates = body.model_dump(exclude_none=True)
    if updates:
        await store.update_user(request.app.state.pool, user_id, updates)
        await store.audit(
            request.app.state.pool,
            identity["sub"], identity["email"],
            "user.update", "user", user_id, updates,
        )

    updated = await store.get_user_by_id(request.app.state.pool, user_id)
    u = dict(updated)
    u.pop("password_hash", None)
    u.pop("token_version", None)
    return u
