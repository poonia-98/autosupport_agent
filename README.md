# AutoSupport v4

Production-grade AI support ticket triage platform.

## Stack

| Component | Technology |
|---|---|
| API | FastAPI + asyncpg + Python 3.10+ |
| Task Queue | ARQ (Redis-backed, distributed) |
| Database | PostgreSQL 16 + full-text search |
| Migrations | Alembic (versioned, reversible) |
| Rate Limiting | Redis sliding window (multi-replica safe) |
| Authentication | PBKDF2-SHA256 + JWT with token_version invalidation |
| Observability | structlog (JSON), Prometheus metrics |

## Quick start (Docker)

```bash
cp .env.example .env
# Edit .env — set SECRET_KEY, ADMIN_EMAIL, ADMIN_PASSWORD at minimum
docker compose up --build
```

Open http://localhost:8001 — login with your `ADMIN_EMAIL` / `ADMIN_PASSWORD`.

## Quick start (local dev)

```bash
# 1. Postgres + Redis via Docker
docker compose up postgres redis -d

# 2. Install deps
pip install -e ".[dev]"

# 3. Set env vars
cp .env.example .env

# 4. Run migrations
alembic upgrade head

# 5. Start API
python main.py

# 6. Start worker (separate terminal)
arq tasks.worker.WorkerSettings
```

## Running tests

```bash
# Fast unit + pipeline tests (no DB needed)
pytest tests/test_domain.py tests/test_pipeline.py -v

# Full API integration tests (needs running Postgres + Redis)
TEST_DATABASE_URL=postgresql+asyncpg://autosupport:autosupport@localhost:5433/autosupport_test \
pytest tests/test_api.py -v
```

## Architecture

```
main.py              FastAPI app factory + lifespan (pool, ARQ, Redis)
api/                 HTTP routers (auth, tickets, analytics, queue, agents, integrations, users, system)
services/            Business logic — ticket, user, SLA, integration
support_agents/      5-agent pipeline: classifier → priority → escalation → responder → router
intelligence/        Keyword router, rules engine, async LLM client (thread-safe cache)
integrations/        Webhook adapter (extensible ABC)
tasks/               ARQ task definitions + WorkerSettings
workflows/           Pipeline orchestrator + domain event emission
domain/              Typed events, event bus, state machine
db/                  asyncpg pool + full store (all queries parameterised)
alembic/             Versioned migrations (up + down)
core/                Config, security, rate limit, middleware, metrics, retry
templates/           SPA dashboard (8 pages, hash routing)
tests/               Unit tests + API integration tests
```

## Scaling

- **API**: horizontal via `docker compose scale api=N` — stateless, pool-per-process
- **Workers**: `docker compose scale worker=N` — each instance runs up to `max_jobs` concurrent jobs
- **Rate limiting**: Redis-backed, so it works correctly across multiple API replicas

## Environment variables

| Variable | Required | Default | Notes |
|---|---|---|---|
| `SECRET_KEY` | **prod** | dev value | `python -c "import secrets; print(secrets.token_hex(32))"` |
| `DATABASE_URL` | yes | pg://localhost:5433/autosupport | asyncpg format for local dev |
| `REDIS_URL` | yes | redis://localhost:6379/0 | shared by API + worker |
| `ADMIN_EMAIL` | yes | admin@example.com | first-run seed |
| `ADMIN_PASSWORD` | **prod** | changeme123 | changed by prod validator |
| `CORS_ORIGINS` | **prod** | `*` | required to be explicit in production |
| `LLM_ENABLED` | no | false | set to true + LLM_API_KEY to enable |
| `ENVIRONMENT` | no | development | development/staging/production |
