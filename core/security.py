import asyncio
import collections
import hashlib
import hmac
import os
import time
from datetime import datetime, timezone, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from core.config import get_settings

_bearer = HTTPBearer(auto_error=False)

_login_attempts: dict[str, collections.deque] = {}
_MAX_ATTEMPTS = 10
_ATTEMPT_WINDOW = 600
_MAX_TRACKED = 5_000


def hash_password(password: str) -> str:
    salt = os.urandom(32)
    key = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
    return salt.hex() + ":" + key.hex()


def _verify_password_sync(password: str, stored_hash: str) -> bool:
    try:
        salt_hex, key_hex = stored_hash.split(":", 1)
        salt = bytes.fromhex(salt_hex)
        key = bytes.fromhex(key_hex)
        candidate = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, 200_000)
        return hmac.compare_digest(candidate, key)
    except Exception:
        return False


async def verify_password(password: str, stored_hash: str) -> bool:
    return await asyncio.to_thread(_verify_password_sync, password, stored_hash)


def _evict_expired_attempts() -> None:
    if len(_login_attempts) < _MAX_TRACKED:
        return
    now = time.monotonic()
    cutoff = now - _ATTEMPT_WINDOW
    dead = [k for k, dq in _login_attempts.items() if not dq or dq[-1] < cutoff]
    for k in dead:
        del _login_attempts[k]


def check_login_rate(email: str) -> bool:
    now = time.monotonic()
    cutoff = now - _ATTEMPT_WINDOW
    dq = _login_attempts.setdefault(email, collections.deque())
    while dq and dq[0] < cutoff:
        dq.popleft()
    return len(dq) < _MAX_ATTEMPTS


def record_failed_login(email: str) -> None:
    _evict_expired_attempts()
    dq = _login_attempts.setdefault(email, collections.deque())
    dq.append(time.monotonic())


def clear_login_attempts(email: str) -> None:
    _login_attempts.pop(email, None)


def create_token(user_id: str, email: str, role: str, token_version: int = 0) -> str:
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "tv": token_version,
        "iat": int(now.timestamp()),
        "exp": int((now + timedelta(minutes=settings.jwt_ttl_minutes)).timestamp()),
    }
    return jwt.encode(payload, settings.secret_key, algorithm="HS256")


def decode_token(token: str) -> dict:
    settings = get_settings()
    try:
        return jwt.decode(token, settings.secret_key, algorithms=["HS256"])
    except jwt.ExpiredSignatureError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    except jwt.InvalidTokenError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Invalid token")


def sign_hmac(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def verify_hmac(secret: str, body: bytes, signature: str) -> bool:
    return hmac.compare_digest(sign_hmac(secret, body), signature)


async def require_auth(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> dict:
    if not credentials:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="Missing credentials")

    payload = decode_token(credentials.credentials)

    # token_version check — invalidates all tokens issued before password change
    from db.pool import get_pool
    from db.store import get_user_by_id

    pool = getattr(request.app.state, "pool", None) or get_pool()
    user = await get_user_by_id(pool, payload["sub"])
    if not user or not user.get("active"):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, detail="User not found or inactive")
    if user.get("token_version", 0) != payload.get("tv", 0):
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            detail="Token invalidated. Please log in again.",
        )
    return payload


async def require_admin(identity: dict = Depends(require_auth)) -> dict:
    if identity.get("role") != "admin":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return identity


async def require_operator(identity: dict = Depends(require_auth)) -> dict:
    if identity.get("role") not in ("admin", "operator"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Operator access required")
    return identity

