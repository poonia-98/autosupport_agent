"""baseline schema

Revision ID: 001
Revises:
Create Date: 2026-03-12
"""

revision = "001"
down_revision = None
branch_labels = None
depends_on = None

from alembic import op
import sqlalchemy as sa


def upgrade() -> None:
    op.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id              TEXT PRIMARY KEY,
            email           TEXT NOT NULL UNIQUE,
            name            TEXT NOT NULL DEFAULT '',
            role            TEXT NOT NULL DEFAULT 'operator',
            password_hash   TEXT NOT NULL,
            token_version   INTEGER NOT NULL DEFAULT 0,
            active          BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS tickets (
            id                    TEXT PRIMARY KEY,
            title                 TEXT NOT NULL,
            description           TEXT NOT NULL DEFAULT '',
            user_id               TEXT REFERENCES users(id) ON DELETE SET NULL,
            priority              TEXT NOT NULL DEFAULT 'medium',
            category              TEXT NOT NULL DEFAULT 'general',
            status                TEXT NOT NULL DEFAULT 'open',
            assigned_team         TEXT,
            assigned_to           TEXT,
            suggested_response    TEXT,
            response_sla_breached BOOLEAN NOT NULL DEFAULT FALSE,
            first_response_at     TIMESTAMPTZ,
            resolved_at           TIMESTAMPTZ,
            source                TEXT NOT NULL DEFAULT 'api',
            integration_ref       TEXT,
            idempotency_key       TEXT UNIQUE,
            search_vector         TSVECTOR,
            created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # GIN index for full-text search
    op.execute("CREATE INDEX IF NOT EXISTS idx_tickets_fts ON tickets USING GIN(search_vector)")
    # Covering indexes for common query patterns
    op.execute("CREATE INDEX IF NOT EXISTS idx_tickets_status_created ON tickets(status, created_at DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tickets_priority_status ON tickets(priority, status)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tickets_assigned_team ON tickets(assigned_team) WHERE assigned_team IS NOT NULL")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tickets_sla ON tickets(response_sla_breached, status, created_at) WHERE response_sla_breached = TRUE")
    op.execute("CREATE INDEX IF NOT EXISTS idx_tickets_created_at ON tickets(created_at DESC)")

    # Trigger to auto-update search_vector
    op.execute("""
        CREATE OR REPLACE FUNCTION tickets_search_vector_update() RETURNS TRIGGER AS $$
        BEGIN
            NEW.search_vector :=
                setweight(to_tsvector('english', coalesce(NEW.title, '')), 'A') ||
                setweight(to_tsvector('english', coalesce(NEW.description, '')), 'B');
            RETURN NEW;
        END
        $$ LANGUAGE plpgsql
    """)
    op.execute("""
        CREATE TRIGGER tickets_search_vector_trigger
        BEFORE INSERT OR UPDATE OF title, description ON tickets
        FOR EACH ROW EXECUTE FUNCTION tickets_search_vector_update()
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS job_log (
            job_id      TEXT PRIMARY KEY,
            ticket_id   TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            status      TEXT NOT NULL DEFAULT 'enqueued',
            error       TEXT,
            attempts    INTEGER NOT NULL DEFAULT 0,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_log_ticket ON job_log(ticket_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_job_log_status ON job_log(status, updated_at DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS agent_events (
            id          BIGSERIAL PRIMARY KEY,
            ticket_id   TEXT NOT NULL REFERENCES tickets(id) ON DELETE CASCADE,
            agent       TEXT NOT NULL,
            result      JSONB,
            duration_ms INTEGER,
            ts          TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_ticket ON agent_events(ticket_id)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_agent_events_ts ON agent_events(ts DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS integrations (
            id           TEXT PRIMARY KEY,
            name         TEXT NOT NULL,
            type         TEXT NOT NULL,
            config       JSONB NOT NULL DEFAULT '{}',
            secret       TEXT,
            status       TEXT NOT NULL DEFAULT 'inactive',
            event_count  INTEGER NOT NULL DEFAULT 0,
            last_sync_at TIMESTAMPTZ,
            sync_error   TEXT,
            created_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    op.execute("""
        CREATE TABLE IF NOT EXISTS integration_events (
            id               BIGSERIAL PRIMARY KEY,
            integration_id   TEXT NOT NULL REFERENCES integrations(id) ON DELETE CASCADE,
            direction        TEXT NOT NULL,
            status           TEXT NOT NULL,
            payload_size     INTEGER,
            ticket_id        TEXT REFERENCES tickets(id) ON DELETE SET NULL,
            error            TEXT,
            ts               TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_integration_events_integration ON integration_events(integration_id, ts DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS audit_log (
            id            BIGSERIAL PRIMARY KEY,
            user_id       TEXT NOT NULL,
            user_email    TEXT NOT NULL,
            action        TEXT NOT NULL,
            resource_type TEXT NOT NULL,
            resource_id   TEXT,
            meta          JSONB,
            ts            TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_user ON audit_log(user_id, ts DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_audit_log_resource ON audit_log(resource_type, resource_id, ts DESC)")

    op.execute("""
        CREATE TABLE IF NOT EXISTS system_log (
            id      BIGSERIAL PRIMARY KEY,
            level   TEXT NOT NULL,
            source  TEXT NOT NULL,
            message TEXT NOT NULL,
            ts      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)
    op.execute("CREATE INDEX IF NOT EXISTS idx_system_log_ts ON system_log(ts DESC)")
    op.execute("CREATE INDEX IF NOT EXISTS idx_system_log_level ON system_log(level, ts DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS system_log CASCADE")
    op.execute("DROP TABLE IF EXISTS audit_log CASCADE")
    op.execute("DROP TABLE IF EXISTS integration_events CASCADE")
    op.execute("DROP TABLE IF EXISTS integrations CASCADE")
    op.execute("DROP TABLE IF EXISTS agent_events CASCADE")
    op.execute("DROP TABLE IF EXISTS job_log CASCADE")
    op.execute("DROP TRIGGER IF EXISTS tickets_search_vector_trigger ON tickets")
    op.execute("DROP FUNCTION IF EXISTS tickets_search_vector_update()")
    op.execute("DROP TABLE IF EXISTS tickets CASCADE")
    op.execute("DROP TABLE IF EXISTS users CASCADE")
