"""
API-level integration tests.
Requires: TEST_DATABASE_URL and TEST_REDIS_URL environment variables.
Run with: pytest tests/test_api.py -v
"""

import os
import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport


def _has_infra() -> bool:
    return bool(os.getenv("TEST_DATABASE_URL"))


pytestmark = pytest.mark.skipif(not _has_infra(), reason="TEST_DATABASE_URL not set")


@pytest_asyncio.fixture
async def client():
    from main import create_app

    _app = create_app()
    async with AsyncClient(transport=ASGITransport(app=_app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client):
    r = await client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert "status" in data
    assert "version" in data


@pytest.mark.asyncio
async def test_login_and_me(client):
    r = await client.post("/api/auth/login", json={
        "email": os.getenv("ADMIN_EMAIL", "admin@example.com"),
        "password": os.getenv("ADMIN_PASSWORD", "changeme123"),
    })
    assert r.status_code == 200
    token = r.json()["access_token"]

    r2 = await client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r2.status_code == 200
    assert r2.json()["role"] == "admin"


@pytest.mark.asyncio
async def test_bad_login_returns_401(client):
    r = await client.post("/api/auth/login", json={"email": "nobody@test.com", "password": "wrong"})
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_unauthenticated_access(client):
    r = await client.get("/api/tickets")
    assert r.status_code == 401


@pytest.mark.asyncio
async def test_create_and_get_ticket(client):
    login = await client.post("/api/auth/login", json={
        "email": os.getenv("ADMIN_EMAIL", "admin@example.com"),
        "password": os.getenv("ADMIN_PASSWORD", "changeme123"),
    })
    token = login.json()["access_token"]
    auth  = {"Authorization": f"Bearer {token}"}

    r = await client.post("/api/tickets", json={
        "title":       "Test ticket from pytest",
        "description": "This is a test description.",
        "priority":    "medium",
    }, headers=auth)
    assert r.status_code == 201
    ticket_id = r.json()["id"]
    assert ticket_id

    r2 = await client.get(f"/api/tickets/{ticket_id}", headers=auth)
    assert r2.status_code == 200
    assert r2.json()["id"] == ticket_id


@pytest.mark.asyncio
async def test_idempotency_key(client):
    login = await client.post("/api/auth/login", json={
        "email": os.getenv("ADMIN_EMAIL", "admin@example.com"),
        "password": os.getenv("ADMIN_PASSWORD", "changeme123"),
    })
    token = login.json()["access_token"]
    auth  = {"Authorization": f"Bearer {token}"}

    payload = {"title": "Idempotent ticket", "idempotency_key": "pytest-idem-001"}

    r1 = await client.post("/api/tickets", json=payload, headers=auth)
    r2 = await client.post("/api/tickets", json=payload, headers=auth)
    assert r1.status_code == 201
    assert r2.status_code == 201
    assert r1.json()["id"] == r2.json()["id"]


@pytest.mark.asyncio
async def test_invalid_search_query_returns_400(client):
    login = await client.post("/api/auth/login", json={
        "email": os.getenv("ADMIN_EMAIL", "admin@example.com"),
        "password": os.getenv("ADMIN_PASSWORD", "changeme123"),
    })
    token = login.json()["access_token"]
    auth  = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/tickets?search=OR+OR", headers=auth)
    assert r.status_code == 400


@pytest.mark.asyncio
async def test_analytics_endpoint(client):
    login = await client.post("/api/auth/login", json={
        "email": os.getenv("ADMIN_EMAIL", "admin@example.com"),
        "password": os.getenv("ADMIN_PASSWORD", "changeme123"),
    })
    token = login.json()["access_token"]
    auth  = {"Authorization": f"Bearer {token}"}

    r = await client.get("/api/analytics", headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert "total_tickets" in data
    assert "by_priority" in data


@pytest.mark.asyncio
async def test_bulk_close(client):
    login = await client.post("/api/auth/login", json={
        "email": os.getenv("ADMIN_EMAIL", "admin@example.com"),
        "password": os.getenv("ADMIN_PASSWORD", "changeme123"),
    })
    token = login.json()["access_token"]
    auth  = {"Authorization": f"Bearer {token}"}

    # create 3 tickets
    ids = []
    for i in range(3):
        r = await client.post("/api/tickets", json={"title": f"Bulk close test {i}"}, headers=auth)
        ids.append(r.json()["id"])

    r = await client.post("/api/tickets/bulk-close", json={"ticket_ids": ids + ["nonexistent-xyz"]}, headers=auth)
    assert r.status_code == 200
    data = r.json()
    assert data["closed"] == 3
    assert "nonexistent-xyz" in data["not_found"]
