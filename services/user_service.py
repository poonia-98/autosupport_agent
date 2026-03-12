import uuid
from typing import Any

import asyncpg
import structlog

from core.exceptions import AuthenticationError, UserNotFound
from core.security import (
    check_login_rate,
    clear_login_attempts,
    create_token,
    hash_password,
    record_failed_login,
    verify_password,
)
from db import store

logger = structlog.get_logger("services.user")


async def login(pool: asyncpg.Pool, email: str, password: str) -> dict[str, Any]:
    if not check_login_rate(email):
        raise AuthenticationError("Too many failed attempts. Try again in 10 minutes.")

    user = await store.get_user_by_email(pool, email)
    if not user or not await verify_password(password, user["password_hash"]):
        record_failed_login(email)
        raise AuthenticationError("Invalid credentials.")

    if not user.get("active"):
        raise AuthenticationError("Account is disabled.")

    clear_login_attempts(email)
    token = create_token(
        user["id"],
        user["email"],
        user["role"],
        user.get("token_version", 0),
    )
    logger.info("user.login", user_id=user["id"])

    return {
        "access_token": token,
        "token_type": "bearer",
        "user_id": user["id"],
        "role": user["role"],
    }


async def create_user(
    pool: asyncpg.Pool,
    email: str,
    name: str,
    role: str,
    password: str,
    actor: dict,
) -> dict[str, Any]:
    existing = await store.get_user_by_email(pool, email)
    if existing:
        from fastapi import HTTPException, status
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail=f"Email {email!r} already registered.",
        )

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(password)

    await store.insert_user(pool, user_id, email, name, role, pw_hash)

    await store.audit(
        pool,
        actor["sub"],
        actor["email"],
        "user.create",
        "user",
        user_id,
        {"email": email, "role": role},
    )

    logger.info("user.created", user_id=user_id, by=actor["email"])

    user = await store.get_user_by_id(pool, user_id)
    u = dict(user)
    u.pop("password_hash", None)
    u.pop("token_version", None)
    return u


async def change_password(
    pool: asyncpg.Pool,
    user_id: str,
    current_password: str,
    new_password: str,
) -> None:
    user = await store.get_user_by_id(pool, user_id)
    if not user:
        raise UserNotFound(user_id)

    if not await verify_password(current_password, user["password_hash"]):
        raise AuthenticationError("Current password is incorrect.")

    new_hash = hash_password(new_password)

    async with pool.acquire() as conn:
        async with conn.transaction():
            await store.update_user(conn, user_id, {"password_hash": new_hash})
            await store.increment_token_version(conn, user_id)

    logger.info("user.password_changed", user_id=user_id)


# ⭐⭐⭐ FIXED SAFE ADMIN SEED ⭐⭐⭐
async def seed_admin(pool: asyncpg.Pool) -> None:
    from core.config import get_settings

    settings = get_settings()

    # idempotent seed — check admin specifically
    existing = await store.get_user_by_email(pool, settings.admin_email)
    if existing:
        return

    user_id = str(uuid.uuid4())
    pw_hash = hash_password(settings.admin_password)

    await store.insert_user(
        pool,
        user_id,
        settings.admin_email,
        "Admin",
        "admin",
        pw_hash,
    )

    logger.info("user.admin_seeded", email=settings.admin_email)