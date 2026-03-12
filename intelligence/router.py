import re
from typing import Any

_CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "billing":         ["billing", "invoice", "refund", "charge", "payment", "fee", "cost", "subscription", "price"],
    "technical":       ["password", "login", "2fa", "access", "account", "api", "integration", "error", "crash", "timeout"],
    "feature_request": ["feature", "request", "suggest", "improvement", "idea", "new"],
    "bug":             ["broken", "fail", "error", "bug", "issue", "crash", "not working", "incorrect", "wrong"],
}

_PRIORITY_KEYWORDS: dict[str, list[str]] = {
    "critical": ["down", "outage", "emergency", "urgent", "production", "blocked", "critical"],
    "high":     ["important", "asap", "priority", "severe", "major"],
    "medium":   ["help", "question", "issue", "minor"],
    "low":      ["feedback", "info", "thanks"],
}


def route_ticket(title: str, description: str) -> dict[str, Any]:
    text = f"{title} {description}".lower()
    if not text.strip():
        return {"category": "general", "priority": "low", "confidence": 1.0}

    cat_scores: dict[str, int] = {}
    for cat, kws in _CATEGORY_KEYWORDS.items():
        score = sum(1 for k in kws if re.search(rf"\b{re.escape(k)}\b", text))
        if score:
            cat_scores[cat] = score

    best_cat, cat_conf = "general", 0.5
    if cat_scores:
        best_cat = max(cat_scores, key=cat_scores.get)  # type: ignore[arg-type]
        total = sum(cat_scores.values())
        cat_conf = min(0.9, cat_scores[best_cat] / total + 0.3)

    pri_scores: dict[str, int] = {}
    for pri, kws in _PRIORITY_KEYWORDS.items():
        score = sum(2 if k in title.lower() else 1 for k in kws if re.search(rf"\b{re.escape(k)}\b", text))
        if score:
            pri_scores[pri] = score

    best_pri, pri_conf = "medium", 0.5
    if pri_scores:
        best_pri = max(pri_scores, key=pri_scores.get)  # type: ignore[arg-type]
        total = sum(pri_scores.values())
        pri_conf = min(0.9, pri_scores[best_pri] / total + 0.3)

    return {
        "category":   best_cat,
        "priority":   best_pri,
        "confidence": round((cat_conf + pri_conf) / 2.0, 3),
    }
