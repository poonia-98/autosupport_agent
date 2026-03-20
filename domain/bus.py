import asyncio
from collections import defaultdict
from collections.abc import Callable
from typing import Any

import structlog

logger = structlog.get_logger("domain.bus")


class EventBus:
    def __init__(self) -> None:
        self._handlers: dict[type, list[Callable]] = defaultdict(list)

    def subscribe(self, event_type: type, handler: Callable) -> None:
        self._handlers[event_type].append(handler)

    async def emit(self, event: Any) -> None:
        handlers = self._handlers.get(type(event), [])
        for h in handlers:
            try:
                if asyncio.iscoroutinefunction(h):
                    await h(event)
                else:
                    h(event)
            except Exception:
                logger.exception(
                    "bus.handler_error",
                    event=type(event).__name__,
                    handler=getattr(h, "__name__", repr(h)),
                )


# module singleton — handlers wired in main.py lifespan
bus = EventBus()

