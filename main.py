import contextlib

import structlog
from arq.connections import create_pool as arq_create_pool, RedisSettings
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from redis.asyncio import Redis

from api import build_router
from core.config import get_settings
from core.logging import configure_logging
from core.middleware import (
    RateLimitMiddleware,
    RequestContextMiddleware,
    SecurityHeadersMiddleware,
)
from db.pool import close_pool, init_pool

logger = structlog.get_logger("main")


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()

    # DB
    app.state.pool = await init_pool()

    # Redis — shared instance for rate limiting
    app.state.redis = Redis.from_url(settings.redis_url, decode_responses=True)

    # ARQ connection — used to enqueue jobs
    arq_settings = RedisSettings.from_dsn(settings.redis_url)
    app.state.arq = await arq_create_pool(arq_settings)

    # Seed admin user on first launch
    from services.user_service import seed_admin
    await seed_admin(app.state.pool)

    logger.info("startup.ready", environment=settings.environment, version=settings.version)

    yield

    await app.state.arq.close(True)
    await app.state.redis.aclose()
    await close_pool()
    logger.info("shutdown.complete")


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging()

    app = FastAPI(
        title     = "AutoSupport",
        version   = settings.version,
        docs_url  = "/docs" if settings.environment != "production" else None,
        redoc_url = None,
        lifespan  = lifespan,
    )

    app.add_middleware(SecurityHeadersMiddleware)
    app.add_middleware(RateLimitMiddleware)
    app.add_middleware(RequestContextMiddleware)
    app.add_middleware(
        CORSMiddleware,
        allow_origins     = settings.cors_origins_list,
        allow_credentials = True,
        allow_methods     = ["*"],
        allow_headers     = ["*"],
    )

    app.include_router(build_router())

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def dashboard():
        from pathlib import Path
        html = (Path(__file__).parent / "templates" / "dashboard.html").read_text()
        return HTMLResponse(html)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn
    s = get_settings()
    uvicorn.run(
        "main:app",
        host    = s.host,
        port    = s.port,
        reload  = s.environment == "development",
        workers = 1,
        log_config = None,   # structlog handles logging
    )
