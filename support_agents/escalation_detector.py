from typing import Any

_SIGNALS = [
    ("critical_intent", lambda c: c.get("intent") in ("technical", "bug") and c.get("suggested_priority") == "critical", 30),
    ("critical_priority", lambda c: c.get("suggested_priority") == "critical", 25),
    ("high_urgency", lambda c: c.get("urgency_score", 0) >= 0.75, 20),
    ("elevated_urgency", lambda c: 0.5 <= c.get("urgency_score", 0) < 0.75, 10),
    ("high_confidence", lambda c: c.get("confidence_score", 0) >= 0.9, 10),
    ("sla_breached", lambda c: c.get("response_sla_breached", False), 15),
]

_ESCALATE_THRESHOLD = 40
_IMMEDIATE_THRESHOLD = 60

_READABLE = {
    "critical_intent": "critical technical or bug issue",
    "critical_priority": "critical priority",
    "high_urgency": "very high urgency",
    "elevated_urgency": "elevated urgency",
    "high_confidence": "high confidence",
    "sla_breached": "SLA response breached",
}


class EscalationDetector:
    name = "escalation_detector"

    async def run(self, ticket_data: dict, classification: dict, ml_signals: dict) -> dict[str, Any]:
        if classification.get("rule_escalation"):
            return {
                "should_escalate": True,
                "immediate": True,
                "escalation_level": 2,
                "escalation_score": 100,
                "triggered_signals": ["hard_rule_override"],
                "reason": "Escalated by deterministic rules engine",
            }

        ctx = {
            **classification,
            "confidence_score": classification.get("intent_confidence", 0),
            "response_sla_breached": ticket_data.get("response_sla_breached", False),
        }

        score = 0
        triggered: list[str] = []
        for name, check_fn, weight in _SIGNALS:
            try:
                if check_fn(ctx):
                    score += weight
                    triggered.append(name)
            except Exception:
                pass

        immediate = score >= _IMMEDIATE_THRESHOLD
        should_escalate = score >= _ESCALATE_THRESHOLD
        level = 2 if immediate else (1 if should_escalate else 0)

        return {
            "should_escalate": should_escalate,
            "immediate": immediate,
            "escalation_level": level,
            "escalation_score": score,
            "triggered_signals": triggered,
            "reason": "; ".join(_READABLE.get(s, s) for s in triggered[:3]) or "No escalation signals",
        }


escalation_detector = EscalationDetector()

