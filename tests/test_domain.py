"""
Domain logic tests — no DB, no network, fast.
"""

import pytest

from core.exceptions import InvalidStateTransition
from domain.ticket import can_transition, validate_transition


class TestTicketStateMachine:
    def test_open_to_in_progress(self):
        assert can_transition("open", "in_progress")

    def test_open_to_closed(self):
        assert can_transition("open", "closed")

    def test_in_progress_to_resolved(self):
        assert can_transition("in_progress", "resolved")

    def test_resolved_can_reopen(self):
        assert can_transition("resolved", "open")

    def test_closed_is_terminal(self):
        assert not can_transition("closed", "open")
        assert not can_transition("closed", "resolved")
        assert not can_transition("closed", "in_progress")

    def test_invalid_transition_raises(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition("closed", "open")

    def test_unknown_from_state_raises(self):
        with pytest.raises(InvalidStateTransition):
            validate_transition("ghost", "open")

    def test_sla_breached_transitions(self):
        assert can_transition("sla_breached", "in_progress")
        assert can_transition("sla_breached", "resolved")
        assert can_transition("sla_breached", "closed")
        assert not can_transition("sla_breached", "open")


class TestRulesEngine:
    def test_billing_keyword_in_title(self):
        from intelligence.rules_engine import apply_rules
        result = apply_rules({"title": "Invoice not received", "description": ""})
        assert result.get("category") == "billing"

    def test_production_down_escalates(self):
        from intelligence.rules_engine import apply_rules
        result = apply_rules({"title": "production down", "description": "site is offline"})
        assert result.get("priority") == "critical"
        assert result.get("should_escalate") is True

    def test_no_match_returns_empty(self):
        from intelligence.rules_engine import apply_rules
        result = apply_rules({"title": "Hello world", "description": "I have a question"})
        assert result == {}


class TestRouter:
    def test_billing_keyword_routes_billing(self):
        from intelligence.router import route_ticket
        out = route_ticket("billing invoice problem", "my subscription charge is wrong")
        assert out["category"] == "billing"

    def test_empty_input_defaults_to_general(self):
        from intelligence.router import route_ticket
        out = route_ticket("", "")
        assert out["category"] == "general"
        assert out["priority"] == "low"
        assert out["confidence"] == 1.0

    def test_confidence_is_bounded(self):
        from intelligence.router import route_ticket
        out = route_ticket("API crash critical production outage", "everything is down")
        assert 0.0 <= out["confidence"] <= 1.0


class TestSecurity:
    def test_hash_and_verify(self):
        from core.security import _verify_password_sync, hash_password
        pw   = "S3cur3P@ss!"
        h    = hash_password(pw)
        assert _verify_password_sync(pw, h)
        assert not _verify_password_sync("wrong", h)

    def test_hashes_are_unique(self):
        from core.security import hash_password
        h1 = hash_password("same")
        h2 = hash_password("same")
        assert h1 != h2  # different salts

    def test_token_roundtrip(self):
        from core.security import create_token, decode_token
        token   = create_token("uid-1", "user@test.com", "admin", token_version=3)
        payload = decode_token(token)
        assert payload["sub"] == "uid-1"
        assert payload["email"] == "user@test.com"
        assert payload["role"] == "admin"
        assert payload["tv"] == 3

    def test_brute_force_tracking(self):
        from core.security import _login_attempts, check_login_rate, record_failed_login
        email = "brutetest@example.com"
        _login_attempts.pop(email, None)
        for _ in range(10):
            record_failed_login(email)
        assert not check_login_rate(email)

    def test_clear_login_attempts(self):
        from core.security import _login_attempts, clear_login_attempts, record_failed_login
        email = "cleartest@example.com"
        _login_attempts.pop(email, None)
        for _ in range(5):
            record_failed_login(email)
        clear_login_attempts(email)
        assert email not in _login_attempts


class TestSLAThresholds:
    def test_critical_response_window(self):
        from models.sla import DEFAULT_SLA, SLASeverity
        t = DEFAULT_SLA[SLASeverity.CRITICAL]
        assert t.first_response_seconds == 900  # 15 min

    def test_low_response_window(self):
        from models.sla import DEFAULT_SLA, SLASeverity
        t = DEFAULT_SLA[SLASeverity.LOW]
        assert t.first_response_seconds == 86_400  # 24h


class TestEscalationDetector:
    @pytest.mark.asyncio
    async def test_rule_override_triggers_immediate(self):
        from support_agents.escalation_detector import escalation_detector
        result = await escalation_detector.run(
            {}, {"rule_escalation": True, "intent": "general", "urgency_score": 0.0}, {}
        )
        assert result["should_escalate"] is True
        assert result["immediate"] is True
        assert result["escalation_level"] == 2

    @pytest.mark.asyncio
    async def test_low_urgency_no_escalation(self):
        from support_agents.escalation_detector import escalation_detector
        result = await escalation_detector.run(
            {}, {"rule_escalation": False, "intent": "general", "urgency_score": 0.0, "suggested_priority": "low"}, {}
        )
        assert result["should_escalate"] is False


class TestPriorityPredictor:
    @pytest.mark.asyncio
    async def test_critical_technical_intent_predicts_critical(self):
        from support_agents.priority_predictor import priority_predictor
        result = await priority_predictor.run(
            {},
            {"intent": "technical", "suggested_priority": "critical", "urgency_score": 0.5},
            {},
        )
        assert result["predicted_priority"] in ("critical", "high")
        assert 0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_no_signals_returns_low(self):
        from support_agents.priority_predictor import priority_predictor
        result = await priority_predictor.run(
            {},
            {"intent": "general", "suggested_priority": "low", "urgency_score": 0.0},
            {},
        )
        assert result["predicted_priority"] == "low"


class TestAutoRouter:
    @pytest.mark.asyncio
    async def test_critical_technical_routes_to_sre(self):
        from support_agents.auto_router import auto_router
        result = await auto_router.run(
            {},
            {"intent": "technical", "suggested_priority": "critical"},
            {"should_escalate": False, "immediate": False},
        )
        assert result["assigned_team"] == "sre_team"
        assert result["queue_priority"] == 1

    @pytest.mark.asyncio
    async def test_billing_routes_to_billing_team(self):
        from support_agents.auto_router import auto_router
        result = await auto_router.run(
            {},
            {"intent": "billing", "suggested_priority": "medium"},
            {"should_escalate": False, "immediate": False},
        )
        assert result["assigned_team"] == "billing_team"

    @pytest.mark.asyncio
    async def test_immediate_escalation_sets_priority_1(self):
        from support_agents.auto_router import auto_router
        result = await auto_router.run(
            {},
            {"intent": "general", "suggested_priority": "low"},
            {"should_escalate": True, "immediate": True},
        )
        assert result["queue_priority"] == 1
