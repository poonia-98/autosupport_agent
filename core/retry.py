import asyncio
import logging
from functools import wraps
from typing import Callable, Tuple, Type

logger = logging.getLogger("retry")


def with_retry(
    max_attempts: int = 3,
    delay: float = 0.5,
    backoff: float = 2.0,
    exceptions: Tuple[Type[Exception], ...] = (Exception,),
) -> Callable:
    def decorator(fn: Callable) -> Callable:
        @wraps(fn)
        async def wrapper(*args, **kwargs):
            last_exc = None
            for attempt in range(max_attempts):
                try:
                    return await fn(*args, **kwargs)
                except exceptions as exc:
                    last_exc = exc
                    if attempt < max_attempts - 1:
                        wait = delay * (backoff ** attempt)
                        logger.warning("retry", extra={"fn": fn.__name__, "attempt": attempt + 1, "wait": wait})
                        await asyncio.sleep(wait)
            raise last_exc
        return wrapper
    return decorator
