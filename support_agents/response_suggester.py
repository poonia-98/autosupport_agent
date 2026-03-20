from typing import Any

_INTENT_TO_TEMPLATE = {
    "billing": "billing_dispute",
    "technical": "service_outage",
    "bug": "bug_report",
    "feature_request": "feature_request",
    "general": "general_inquiry",
}

_TEMPLATES: dict[str, list[str]] = {
    "billing_dispute": [
        "We apologize for the billing issue. Our team will review your account and resolve any discrepancy within 1 business day.",
        "I've flagged this billing concern to our accounts team. You'll receive a detailed statement and resolution within 24 hours.",
    ],
    "service_outage": [
        "We're aware of the service disruption. Our on-call team is actively investigating. Status updates every 30 minutes.",
        "A critical incident has been opened. Our engineering team is working on immediate mitigation.",
    ],
    "bug_report": [
        "Thank you for the detailed bug report. We've created a ticket in our engineering queue and will investigate promptly.",
        "We've reproduced the issue internally and assigned it to our engineering team.",
    ],
    "feature_request": [
        "Thank you for the suggestion. We've added it to our product backlog for the next planning cycle.",
        "Great idea. We've logged this as a feature request and will review it in sprint planning.",
    ],
    "general_inquiry": [
        "Thank you for reaching out. Our support team will respond within 4 business hours.",
        "We've received your message and will get back to you with a detailed response shortly.",
    ],
}


class ResponseSuggester:
    name = "response_suggester"

    async def run(self, ticket_data: dict, classification: dict, escalation: dict) -> dict[str, Any]:
        intent = classification.get("intent", "general")
        template_key = _INTENT_TO_TEMPLATE.get(intent, "general_inquiry")
        templates = _TEMPLATES[template_key]

        idx = 1 if classification.get("urgency_score", 0) >= 0.5 and len(templates) > 1 else 0
        suggestion = templates[idx]

        if escalation.get("should_escalate"):
            suggestion += " This ticket has been escalated to our senior support team for priority handling."
        if ticket_data.get("response_sla_breached"):
            suggestion += " Note: This has been flagged as an SLA-at-risk item."

        return {
            "suggested_response": suggestion,
            "intent": intent,
            "actions": self._build_actions(classification, escalation, ticket_data),
        }

    @staticmethod
    def _build_actions(classification: dict, escalation: dict, ticket_data: dict) -> list[str]:
        actions: list[str] = []
        intent = classification.get("intent", "")

        if escalation.get("immediate"):
            actions.append("page_on_call_engineer")
        elif escalation.get("should_escalate"):
            actions.append("notify_senior_support")

        if intent == "technical" and classification.get("suggested_priority") == "critical":
            actions += ["create_incident_record", "update_status_page"]
        elif intent == "billing":
            actions.append("review_billing_account")

        if ticket_data.get("response_sla_breached"):
            actions.append("sla_breach_notification")

        return actions or ["assign_to_available_agent"]


response_suggester = ResponseSuggester()

