"""
Worker entrypoint.

Run with:
    arq tasks.worker.WorkerSettings

Or via the Makefile / docker-compose service.
"""


import structlog
from arq import cron
from arq.connections import RedisSettings

from core.config import get_settings
from core.logging import configure_logging
from db.pool import close_pool, init_worker_pool
from tasks.classify import classify_ticket

logger = structlog.get_logger("worker")
settings = get_settings()


async def startup(ctx: dict) -> None:
    configure_logging()
    ctx["pool"] = await init_worker_pool()
    logger.info("worker.startup")


async def shutdown(ctx: dict) -> None:
    await close_pool()
    logger.info("worker.shutdown")


async def sla_sweep(ctx: dict) -> None:
    """Cron task: mark response-SLA-breached tickets."""
    from services.sla_service import run_sla_sweep
    pool    = ctx["pool"]
    count   = await run_sla_sweep(pool)
    if count:
        logger.info("sla_sweep.breached", count=count)


async def prune_logs(ctx: dict) -> None:
    """Cron task: purge old system and audit logs."""
    from db.store import prune_logs as do_prune
    pool = ctx["pool"]
    await do_prune(pool)
    logger.info("prune_logs.done")


def _redis_settings() -> RedisSettings:
    s = get_settings()
    # RedisSettings accepts redis://host:port/db
    return RedisSettings.from_dsn(s.redis_url)


class WorkerSettings:
    functions      = [classify_ticket]
    on_startup     = startup
    on_shutdown    = shutdown
    redis_settings = _redis_settings()
    max_jobs       = settings.queue_max_jobs
    job_timeout    = settings.queue_job_timeout
    max_tries      = settings.queue_max_tries
    keep_result    = 3600   # keep job result for 1 hour
    retry_jobs     = True
    health_check_interval = 30

    # Cron tasks — run in the same worker process
    cron_jobs = [
        cron(sla_sweep, minute={0, 15, 30, 45}),   # every 15 min
        cron(prune_logs, hour=3, minute=0),          # 3am daily
    ]


if __name__ == "__main__":
    import arq.cli
    arq.cli.main()
