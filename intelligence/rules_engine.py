from typing import Any


def apply_rules(ticket: dict[str, Any]) -> dict[str, Any]:
    """Deterministic hard rules evaluated before semantic/LLM classification."""
    title = ticket.get("title", "").lower()
    desc = ticket.get("description", "").lower()
    text = f"{title} {desc}"
    result: dict[str, Any] = {}

    if any(k in title for k in ["billing", "invoice", "refund", "charge", "payment", "fee"]):
        result["category"] = "billing"
    elif any(k in title for k in ["password", "login", "2fa", "access", "account"]):
        result["category"] = "technical"

    meta_tier = ticket.get("metadata", {}).get("tier", "") if isinstance(ticket.get("metadata"), dict) else ""
    if "vip" in meta_tier.lower():
        result["priority"] = "high"
        result["should_escalate"] = True
    elif "production down" in text or "outage" in text or "data loss" in text:
        result["priority"] = "critical"
        result["should_escalate"] = True
        result["category"] = "technical"

    return result

