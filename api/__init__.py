from fastapi import APIRouter

from api.agents import router as agents_router
from api.analytics import router as analytics_router
from api.auth import router as auth_router
from api.integrations import router as integrations_router
from api.queue import router as queue_router
from api.system import router as system_router
from api.tickets import router as tickets_router
from api.users import router as users_router


def build_router() -> APIRouter:
    root = APIRouter()
    root.include_router(auth_router)
    root.include_router(tickets_router)
    root.include_router(analytics_router)
    root.include_router(queue_router)
    root.include_router(agents_router)
    root.include_router(integrations_router)
    root.include_router(users_router)
    root.include_router(system_router)
    return root
