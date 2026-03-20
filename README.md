# AutoSupport

AutoSupport is a production-style autonomous support operations platform for teams that want to intake, classify, prioritise, route, monitor, and improve support work without relying on manual triage as the system of record.

It combines a FastAPI backend, PostgreSQL, Redis, ARQ workers, a five-stage agent pipeline, operational analytics, and a live control-room UI into one cohesive support operations system.

## What Problem It Solves

Support teams usually lose time and money in the same places:

- Tickets arrive through multiple channels with inconsistent structure.
- Humans spend the first few minutes of every ticket doing repetitive triage work.
- Priority and escalation decisions depend on who happens to read the ticket first.
- Backlog and queue pressure are hard to see until SLAs are already at risk.
- Integration failures and worker issues stay hidden behind log files.
- Managers cannot easily answer, "What is the system doing right now?"

AutoSupport exists to reduce that operational drag.

## What The Product Does

AutoSupport takes inbound support work and turns it into an observable, automatable pipeline:

1. Accepts tickets from API calls or webhook integrations.
2. Persists them with searchable metadata in PostgreSQL.
3. Enqueues autonomous processing in Redis-backed ARQ workers.
4. Runs a five-stage support pipeline:
   - `ticket_classifier`
   - `priority_predictor`
   - `escalation_detector`
   - `response_suggester`
   - `auto_router`
5. Writes assignments, suggested responses, escalation state, and analytics back to the database.
6. Exposes live operational intelligence through APIs and the control-room UI.

## Why It Is Useful

AutoSupport is not just a ticket CRUD app.

It is useful because it connects three things that are often separate:

- Ticket execution
- Operational telemetry
- Human oversight

That means one system can answer all of these at the same time:

- What tickets are coming in?
- Which ones are risky?
- What are the agents doing?
- Is the queue healthy?
- Are integrations failing?
- Are operators overloaded?

## Time And Money Savings

The exact savings depend on ticket volume, team cost, and automation rate, so the numbers below are illustrative rather than guaranteed.

### Example ROI Scenario

Assume:

- 100 tickets per day
- 2 to 3 minutes of manual triage per ticket
- blended support cost of $35 to $60 per hour

Estimated savings from automated triage:

| Scenario | Daily Time Saved | Monthly Time Saved | Monthly Cost Avoided |
|---|---:|---:|---:|
| 100 tickets/day at 2 min each | 3.3 hours | ~73 hours | ~$2,555 to ~$4,380 |
| 100 tickets/day at 3 min each | 5.0 hours | ~110 hours | ~$3,850 to ~$6,600 |
| 250 tickets/day at 2 min each | 8.3 hours | ~183 hours | ~$6,405 to ~$10,980 |

Where additional value often shows up:

- fewer SLA misses because risky tickets surface earlier
- faster routing to the right team
- fewer repeated retries and less queue blindness
- lower supervisor overhead because the control room is already operationally summarised

## How AutoSupport Works

### End-To-End Flow

```mermaid
flowchart LR
    A[API Client or Webhook] --> B[FastAPI API Layer]
    B --> C[(PostgreSQL)]
    B --> D[(Redis / ARQ)]
    D --> E[ARQ Worker]
    E --> F[Workflow Engine]
    F --> G[Ticket Classifier]
    G --> H[Priority Predictor]
    H --> I[Escalation Detector]
    I --> J[Response Suggester]
    J --> K[Auto Router]
    K --> C
    C --> L[Analytics + Queue + Audit APIs]
    L --> M[Control Room UI]
```

### Runtime Sequence

```mermaid
sequenceDiagram
    participant Client
    participant API as FastAPI API
    participant DB as PostgreSQL
    participant Redis as Redis/ARQ
    participant Worker as ARQ Worker
    participant Engine as Workflow Engine

    Client->>API: POST /api/tickets
    API->>DB: insert ticket
    API->>Redis: enqueue classify_ticket
    API->>DB: upsert job status = enqueued
    Worker->>DB: job status = running
    Worker->>Engine: run_pipeline(ticket)
    Engine->>Engine: classify -> priority -> escalation -> response -> routing
    Engine->>DB: record agent events + ticket updates
    Worker->>DB: job status = done
    Client->>API: GET /api/analytics/ops
    API->>DB: aggregate queue, ticket, SLA, and agent telemetry
    API-->>Client: operational intelligence payload
```

## What Pain It Removes

### Before AutoSupport

- Triage is slow and repetitive.
- Priority is subjective.
- Escalations are late.
- Queue issues are discovered reactively.
- Support leaders depend on dashboards that lag reality.
- Ticket systems answer "what exists," but not "what is happening."

### With AutoSupport

- New tickets are automatically classified and routed.
- Priority and escalation signals are computed consistently.
- Queue state and retry pressure are visible immediately.
- Agent timings and failure rates are observable.
- SLA risk is surfaced before it becomes a fire drill.
- Developers and operators share one operational picture.

## Core Product Capabilities

| Capability | What It Means |
|---|---|
| Autonomous ticket triage | Tickets are classified, prioritised, escalated, and routed by a worker-driven pipeline |
| Queue visibility | Job status, retries, active work, and failures are exposed through APIs and UI |
| Operational intelligence | Throughput, backlog, SLA heatmaps, agent performance, and event streams are available live |
| Human oversight | Operators can inspect, edit, retry, bulk close, and resolve work from the UI |
| Integration ingestion | External systems can submit tickets through webhook-style adapters |
| Auditability | Ticket actions, integration changes, and user operations are written to audit logs |
| Production-style safety | JWT auth, token invalidation, Redis-backed rate limiting, structured logging, and metrics are built in |

## The Five-Agent Pipeline

| Agent | Purpose |
|---|---|
| `ticket_classifier` | Detects intent/category from ticket content |
| `priority_predictor` | Assigns urgency based on support signals |
| `escalation_detector` | Decides whether the ticket needs human escalation |
| `response_suggester` | Generates a response draft and action guidance |
| `auto_router` | Assigns the ticket to the right team and engineer |

The pipeline is orchestrated in [`workflows/engine.py`](./workflows/engine.py) and executed asynchronously by [`tasks/classify.py`](./tasks/classify.py).

## Architecture

### High-Level Components

| Layer | Responsibility | Key Files |
|---|---|---|
| UI | Control-room interface for ops, tickets, queue, agents, integrations, users, system status | `templates/dashboard.html` |
| API | Authenticated REST endpoints for tickets, analytics, queue, system, agents, users, integrations | `api/` |
| Services | Ticket creation, user management, SLA evaluation, integration orchestration | `services/` |
| Workflow | Multi-stage autonomous execution pipeline and stage timing | `workflows/engine.py`, `support_agents/` |
| Queue | Background processing and scheduled maintenance work | `tasks/worker.py`, `tasks/classify.py` |
| Data | Database access, queries, telemetry aggregation, audit storage | `db/store.py`, `db/pool.py`, `alembic/` |
| Core platform | Config, auth, middleware, logging, metrics, retries, rate limits | `core/` |

### Operational Data Already Exposed

AutoSupport already provides enterprise-grade signals through its backend:

- queue depth
- running and failed jobs
- retry counts
- ticket ingress and resolution rates
- backlog trends
- SLA exposure
- agent average latency
- agent p95 latency
- agent error rate
- executions per minute
- ticket pipeline timing
- slow-ticket outliers
- system logs
- audit logs

## Product Structure

```text
autosupport/
├── api/                 # FastAPI route modules
├── core/                # config, auth, middleware, metrics, logging
├── db/                  # asyncpg pool and SQL-backed store layer
├── domain/              # events, domain types, event bus
├── integrations/        # webhook adapter abstraction and implementations
├── intelligence/        # LLM client, rules engine, routing logic
├── models/              # request/response and domain-facing models
├── plugins/             # extension points
├── services/            # ticket, user, integration, SLA logic
├── support_agents/      # five support agents
├── tasks/               # ARQ worker entrypoint and jobs
├── templates/           # live control-room UI
├── tests/               # domain, pipeline, and API tests
├── workflows/           # orchestration engine
├── Dockerfile           # API image
├── Dockerfile.worker    # worker image
├── docker-compose.yml   # local multi-service stack
├── alembic.ini          # migration config
└── pyproject.toml       # package metadata and dev dependencies
```

## API Surface Summary

| Area | Endpoints |
|---|---|
| Auth | `/api/auth/login`, `/api/auth/me`, `/api/auth/change-password` |
| Tickets | `/api/tickets`, `/api/tickets/{id}`, `/api/tickets/{id}/resolve`, `/api/tickets/bulk-close` |
| Analytics | `/api/analytics`, `/api/analytics/time-series`, `/api/analytics/sla`, `/api/analytics/ops` |
| Queue | `/api/queue`, `/api/queue/{ticket_id}/retry` |
| Agents | `/api/agents`, `/api/agents/events` |
| Integrations | `/api/integrations`, `/api/integrations/{id}/test`, `/api/integrations/{id}/ingest`, `/api/integrations/{id}/events` |
| Users | `/api/users`, `/api/users/{id}` |
| System | `/health`, `/metrics`, `/api/system/log`, `/api/audit` |

## UI Summary

The control-room UI is a single-page operational console with sections for:

- Dashboard
- Tickets
- Queue
- Agents
- Integrations
- Users
- System

It is designed around operational signal density rather than admin CRUD forms.

## Local Development

### Option 1: Docker Compose

```bash
cp .env.example .env
docker compose up -d --build
```

Open: `http://localhost:8001`

Default local admin:

- email: `admin@example.com`
- password: `changeme123`

### Option 2: Local Python + Docker Infra

```bash
# 1. Start database and redis only
docker compose up -d postgres redis

# 2. Install dependencies
pip install -e ".[dev]"

# 3. Create local env file
cp .env.example .env

# 4. Run migrations
alembic upgrade head

# 5. Start API
python main.py

# 6. Start workers in another terminal
arq tasks.worker.WorkerSettings
```

## How Developers Can Use It

### 1. Log In And Inspect The Control Room

- open `http://localhost:8001`
- sign in with the seeded admin account
- inspect queue, agents, system, and ticket telemetry

### 2. Create A Ticket

```bash
curl -X POST http://localhost:8001/api/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"admin@example.com","password":"changeme123"}'
```

Use the returned token:

```bash
curl -X POST http://localhost:8001/api/tickets \
  -H "Authorization: Bearer <TOKEN>" \
  -H "Content-Type: application/json" \
  -d '{
    "title": "Production billing checkout is timing out",
    "description": "Multiple customers report payment failures after clicking pay now.",
    "priority": "high",
    "category": "billing"
  }'
```

### 3. Inspect Operational Telemetry

```bash
curl http://localhost:8001/api/analytics/ops?hours=24\&agent_window_minutes=60 \
  -H "Authorization: Bearer <TOKEN>"
```

### 4. Retry A Failed Queue Job

```bash
curl -X POST http://localhost:8001/api/queue/<ticket_id>/retry \
  -H "Authorization: Bearer <TOKEN>"
```

### 5. Add An Integration

Use the UI or create one via API, then call the generated ingest URL to simulate external systems pushing tickets into AutoSupport.

## How Developers Can Test It

### Fast Local Tests

```bash
pytest tests/test_domain.py tests/test_pipeline.py -v
```

### Full Test Suite

```bash
pytest -q
```

### API Integration Tests With Live Infra

```bash
set TEST_DATABASE_URL=postgresql+asyncpg://autosupport:autosupport@localhost:5433/autosupport
set DATABASE_URL=postgresql+asyncpg://autosupport:autosupport@localhost:5433/autosupport
set REDIS_URL=redis://localhost:6379/0
pytest tests/test_api.py -v
```

### Manual Smoke Checklist

1. Sign in from the browser.
2. Create a new ticket.
3. Confirm the queue shows an enqueued or running job.
4. Open the Agents page and confirm events appear.
5. Open the Dashboard and verify throughput, backlog, and SLA panels update.
6. Resolve or bulk-close tickets and confirm the analytics shift.

## Configuration

| Variable | Required | Default | Notes |
|---|---|---|---|
| `ENVIRONMENT` | no | `development` | `development`, `staging`, or `production` |
| `SECRET_KEY` | yes in prod | dev value | Must be changed for production |
| `DATABASE_URL` | yes | local dev default | Asyncpg-style PostgreSQL URL |
| `REDIS_URL` | yes | `redis://localhost:6379/0` | Shared by API and workers |
| `ADMIN_EMAIL` | yes | `admin@example.com` | Seeded admin user |
| `ADMIN_PASSWORD` | yes in prod | `changeme123` | Must be changed for production |
| `CORS_ORIGINS` | yes in prod | `*` | Must be explicit in production |
| `LLM_ENABLED` | no | `false` | Enables optional LLM path |
| `LLM_API_KEY` | no | empty | Required only when `LLM_ENABLED=true` |
| `QUEUE_MAX_JOBS` | no | `10` | Max concurrent jobs per worker process |

## Observability And Safety

AutoSupport includes:

- structured JSON logging via `structlog`
- Prometheus metrics at `/metrics`
- system log and audit log APIs
- retry-aware queue status
- JWT auth with token invalidation support
- Redis-backed rate limiting
- production environment validation guards

## CI/CD

This repository includes GitHub Actions workflows for both CI and container delivery:

### CI

The CI workflow:

- installs the project with dev dependencies
- provisions PostgreSQL and Redis services
- runs Alembic migrations
- runs `ruff check .`
- runs `pytest -q`
- builds both Docker images to catch packaging drift

### CD

The CD workflow:

- runs on tag pushes like `v4.0.0`
- also supports manual `workflow_dispatch`
- builds the API and worker images
- publishes them to GitHub Container Registry (GHCR)

This gives the project a practical delivery path without hardcoding a cloud provider.

## Recommended Release Flow

```text
feature branch
  -> pull request
  -> CI passes
  -> merge to main
  -> create release tag (example: v4.0.1)
  -> GitHub Actions builds and publishes versioned images
  -> deployment environment pulls the new image tags
```

## Included Workflows

- `.github/workflows/ci.yml`
- `.github/workflows/cd.yml`

## Why AutoSupport Matters

AutoSupport is useful because it makes support operations measurable and automatable at the same time.

Instead of only storing tickets, it gives teams:

- autonomous triage
- operational intelligence
- visible queue behaviour
- explainable routing
- failure and SLA awareness
- a developer-friendly local stack

That combination is what turns a helpdesk tool into an operations system.
