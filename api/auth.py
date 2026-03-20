from fastapi import APIRouter, Depends, HTTPException, Request, status

from core.exceptions import AuthenticationError
from core.security import require_auth
from models.user import ChangePasswordRequest, LoginRequest
from services import user_service

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.post("/login")
async def login(body: LoginRequest, request: Request):
    pool = request.app.state.pool
    try:
        return await user_service.login(pool, body.email, body.password)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail=str(exc))


@router.get("/me")
async def me(identity: dict = Depends(require_auth)):
    return {"user_id": identity["sub"], "email": identity["email"], "role": identity["role"]}


@router.post("/change-password", status_code=status.HTTP_200_OK)
async def change_password(
    body: ChangePasswordRequest,
    request: Request,
    identity: dict = Depends(require_auth),
):
    pool = request.app.state.pool
    try:
        await user_service.change_password(pool, identity["sub"], body.current_password, body.new_password)
    except AuthenticationError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc))
    return {"ok": True}

