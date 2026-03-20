"""
Pipeline integration test — runs the full 5-agent workflow against a fake ticket.
No DB or network required.
"""

import pytest


@pytest.mark.asyncio
async def test_full_pipeline_general_ticket():
    from workflows.engine import run_pipeline

    ticket = {
        "id": "test-001",
        "title": "I have a billing question",
        "description": "My invoice seems incorrect for this month.",
        "priority": "medium",
        "category": "general",
        "status": "open",
        "response_sla_breached": False,
    }

    result = await run_pipeline(ticket, correlation_id="test-corr-001")

    assert "intent" in result
    assert result.get("intent") in ("billing", "technical", "bug", "feature_request", "general")
    assert "predicted_priority" in result
    assert "assigned_team" in result
    assert "suggested_response" in result
    assert result["suggested_response"]
    assert "audit" in result
    assert "audit_passed" in result["audit"]
    assert "agent_trace" in result
    assert set(result["agent_trace"]) == {
        "ticket_classifier",
        "priority_predictor",
        "escalation_detector",
        "response_suggester",
        "auto_router",
    }
    assert result["pipeline_duration_ms"] >= 1
    assert all(stage.get("duration_ms", 0) >= 1 for stage in result["agent_trace"].values())


@pytest.mark.asyncio
async def test_full_pipeline_critical_outage():
    from workflows.engine import run_pipeline

    ticket = {
        "id": "test-002",
        "title": "production down — complete outage",
        "description": "All users cannot log in. The entire platform is offline.",
        "priority": "critical",
        "category": "technical",
        "status": "open",
        "response_sla_breached": False,
    }

    result = await run_pipeline(ticket, correlation_id="test-corr-002")

    assert result.get("intent") == "technical"
    escalation = result.get("escalation", {})
    assert escalation.get("should_escalate") is True
    assert result.get("assigned_team") in ("sre_team", "backend_team")


@pytest.mark.asyncio
async def test_pipeline_sla_breached_ticket():
    from workflows.engine import run_pipeline

    ticket = {
        "id": "test-003",
        "title": "login issue",
        "description": "Cannot log in",
        "priority": "high",
        "category": "technical",
        "status": "sla_breached",
        "response_sla_breached": True,
    }

    result = await run_pipeline(ticket)
    # SLA breached should contribute to escalation score
    escalation = result.get("escalation", {})
    assert escalation.get("escalation_score", 0) > 0


@pytest.mark.asyncio
async def test_pipeline_llm_disabled_still_works():
    """Pipeline must function correctly even when LLM is disabled."""
    from workflows.engine import run_pipeline

    ticket = {
        "id": "test-004",
        "title": "feature request: dark mode",
        "description": "Would love a dark theme for the dashboard.",
        "priority": "low",
        "category": "feature_request",
        "status": "open",
        "response_sla_breached": False,
    }

    result = await run_pipeline(ticket)
    assert result.get("intent") == "feature_request"
    assert result.get("assigned_team") == "product_team"
    assert all((stage.get("duration_ms") or 0) >= 1 for stage in result.get("agent_trace", {}).values())


@pytest.mark.asyncio
async def test_bus_events_emitted():
    """TicketClassified event must be emitted from the pipeline."""
    from domain.bus import bus
    from domain.events import TicketClassified
    from workflows.engine import run_pipeline

    received: list = []
    bus.subscribe(TicketClassified, lambda e: received.append(e))

    ticket = {
        "id": "test-005",
        "title": "API returns 500",
        "description": "The /v1/data endpoint crashes",
        "priority": "high",
        "category": "bug",
        "status": "open",
        "response_sla_breached": False,
    }

    await run_pipeline(ticket, correlation_id="corr-005")

    matching = [e for e in received if e.ticket_id == "test-005"]
    assert len(matching) >= 1
    assert matching[0].correlation_id == "corr-005"

