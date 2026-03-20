from typing import Any

from db.store import get_available_engineer

_ROUTING_RULES: list[tuple[frozenset[str], str | None, str, int]] = [
    (frozenset({"technical", "bug"}), "critical", "sre_team", 1),
    (frozenset({"technical"}), "high", "sre_team", 2),
    (frozenset({"technical"}), None, "backend_team", 3),
    (frozenset({"bug"}), "high", "backend_team", 2),
    (frozenset({"bug"}), None, "backend_team", 3),
    (frozenset({"billing"}), None, "billing_team", 2),
    (frozenset({"feature_request"}), None, "product_team", 4),
    (frozenset({"general"}), None, "tier1_support", 3),
]

_TEAM_SKILLS: dict[str, list[str]] = {
    "sre_team": ["infrastructure", "incidents", "kubernetes"],
    "backend_team": ["api", "database", "performance", "bugs"],
    "billing_team": ["payments", "subscriptions", "refunds"],
    "product_team": ["features", "roadmap"],
    "tier1_support": ["general", "documentation"],
}


class AutoRouter:
    name = "auto_router"

    async def run(self, ticket_data: dict, classification: dict, escalation: dict) -> dict[str, Any]:
        intent = classification.get("intent", "general")
        priority = classification.get("suggested_priority", "medium")

        team, queue_priority = self._match(intent, priority)

        if escalation.get("immediate"):
            queue_priority = 1
        elif escalation.get("should_escalate") and queue_priority > 1:
            queue_priority -= 1

        skills = _TEAM_SKILLS.get(team, ["general"])
        assigned_to = get_available_engineer(skills)

        return {
            "assigned_team": team,
            "assigned_engineer": assigned_to,
            "queue_priority": queue_priority,
            "skills_needed": skills,
            "routing_reason": (f"intent={intent} priority={priority}" + (" escalated" if escalation.get("should_escalate") else "")),
        }

    @staticmethod
    def _match(intent: str, priority: str) -> tuple[str, int]:
        for intent_set, pri_filter, team, qp in _ROUTING_RULES:
            if intent in intent_set and pri_filter == priority:
                return team, qp
        for intent_set, pri_filter, team, qp in _ROUTING_RULES:
            if intent in intent_set and pri_filter is None:
                return team, qp
        return "tier1_support", 3


auto_router = AutoRouter()

