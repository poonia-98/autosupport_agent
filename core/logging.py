import logging
import sys
from typing import Any

import structlog

from core.config import get_settings


def configure_logging() -> None:
    settings = get_settings()
    level = getattr(logging, settings.log_level, logging.INFO)

    processors: list[Any] = [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.ExceptionRenderer(),
    ]

    if settings.log_format == "json":
        processors.append(structlog.processors.JSONRenderer())
    else:
        processors.append(structlog.dev.ConsoleRenderer(colors=sys.stdout.isatty()))

    structlog.configure(
        processors=processors,
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.stdlib.BoundLogger,
        cache_logger_on_first_use=True,
    )

    logging.basicConfig(format="%(message)s", stream=sys.stdout, level=level)

    for noisy in ("uvicorn.access", "uvicorn.error", "asyncpg"):
        logging.getLogger(noisy).setLevel(
            logging.DEBUG if settings.debug else logging.WARNING
        )


def get_logger(name: str) -> structlog.BoundLogger:
    return structlog.get_logger(name)


def bind_request_context(request_id: str, path: str, method: str) -> None:
    structlog.contextvars.bind_contextvars(
        request_id=request_id,
        path=path,
        method=method,
    )


def bind_job_context(job_id: str, correlation_id: str, task: str) -> None:
    """Called at the start of each ARQ worker task."""
    structlog.contextvars.bind_contextvars(
        job_id=job_id,
        correlation_id=correlation_id,
        task=task,
    )


def clear_context() -> None:
    structlog.contextvars.clear_contextvars()
