try:
    from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, Histogram, generate_latest

    _PROMETHEUS = True
except ImportError:
    _PROMETHEUS = False

if _PROMETHEUS:
    ticket_created = Counter("autosupport_tickets_created_total", "Tickets created", ["priority"])
    ticket_processed = Counter("autosupport_tickets_processed_total", "Tickets processed", ["status"])
    agent_duration = Histogram("autosupport_agent_duration_seconds", "Agent run duration", ["agent"])
    pipeline_duration = Histogram("autosupport_pipeline_duration_seconds", "Pipeline end-to-end duration")
    queue_depth = Gauge("autosupport_queue_depth", "Pending jobs in queue")
    db_pool_size = Gauge("autosupport_db_pool_size", "Active DB connections")
else:

    class _Noop:
        def labels(self, **_):
            return self

        def inc(self, *_):
            pass

        def observe(self, *_):
            pass

        def set(self, *_):
            pass

    ticket_created = ticket_processed = agent_duration = pipeline_duration = _Noop()
    queue_depth = db_pool_size = _Noop()


def metrics_response() -> tuple:
    if not _PROMETHEUS:
        return None, None
    return generate_latest(), CONTENT_TYPE_LATEST

