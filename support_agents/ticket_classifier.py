import logging
from typing import Any

from intelligence.router import route_ticket
from intelligence.rules_engine import apply_rules

logger = logging.getLogger("agent.ticket_classifier")


class TicketClassifier:
    name = "ticket_classifier"

    async def run(self, ticket_data: dict[str, Any]) -> dict[str, Any]:
        title = ticket_data.get("title", "")
        description = ticket_data.get("description", "")
        ticket_id = ticket_data.get("id", "unknown")

        rules_out = apply_rules(ticket_data)
        semantic_out = route_ticket(title, description)
        confidence = semantic_out.get("confidence", 0.0)

        llm_out = None
        if confidence < 0.55 and not rules_out:
            llm_out = await self._try_llm(ticket_id, title, description)

        if llm_out:
            category = llm_out["category"]
            priority = llm_out["priority"]
            confidence = llm_out["confidence"]
        else:
            category = semantic_out.get("category", "general")
            priority = semantic_out.get("priority", "medium")

        if rules_out:
            category = rules_out.get("category", category)
            if "priority" in rules_out:
                priority = rules_out["priority"]
                confidence = 1.0

        return {
            "intent": category,
            "intent_confidence": round(confidence, 3),
            "suggested_category": category,
            "suggested_priority": priority,
            "urgency_score": 0.5 if priority in ("high", "critical") else 0.1,
            "rule_escalation": rules_out.get("should_escalate", False),
            "llm_used": llm_out is not None,
        }

    @staticmethod
    async def _try_llm(ticket_id: str, title: str, description: str) -> Any:
        from core.config import get_settings

        settings = get_settings()
        if not settings.llm_enabled or not settings.llm_api_key:
            return None
        try:
            from intelligence.llm_client import classify

            return await classify(ticket_id, title, description)
        except Exception as exc:
            logger.warning("ticket_classifier.llm_skip", extra={"ticket_id": ticket_id, "reason": str(exc)})
            return None


ticket_classifier = TicketClassifier()

