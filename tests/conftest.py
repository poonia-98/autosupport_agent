"""
Test configuration.

For full integration tests, set TEST_DATABASE_URL:
    TEST_DATABASE_URL=postgresql+asyncpg://user:pass@localhost:5432/autosupport_test pytest

Without it, DB-dependent tests are skipped automatically.
"""

import os

import pytest
import pytest_asyncio

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("SECRET_KEY", "test-secret-key-" + "x" * 32)
os.environ.setdefault("ADMIN_PASSWORD", "TestPass123!")


@pytest.fixture(scope="session")
def settings():
    from core.config import get_settings

    return get_settings()


@pytest_asyncio.fixture
async def app(settings):
    """Full ASGI app with lifespan — requires live Postgres + Redis."""
    if not os.getenv("TEST_DATABASE_URL"):
        pytest.skip("TEST_DATABASE_URL not set")
    from httpx import ASGITransport, AsyncClient

    from main import create_app

    _app = create_app()
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as client:
        async with _app.router.lifespan_context(_app):
            yield client


@pytest.fixture
def mock_pool(mocker):
    """Lightweight pool mock for unit tests that don't need a real DB."""
    pool = mocker.AsyncMock()
    pool.fetchrow = mocker.AsyncMock(return_value=None)
    pool.fetchval = mocker.AsyncMock(return_value=0)
    pool.fetch = mocker.AsyncMock(return_value=[])
    pool.execute = mocker.AsyncMock(return_value="UPDATE 0")
    pool.acquire = mocker.MagicMock(return_value=mocker.AsyncMock(__aenter__=mocker.AsyncMock(return_value=pool), __aexit__=mocker.AsyncMock(return_value=False)))
    return pool

