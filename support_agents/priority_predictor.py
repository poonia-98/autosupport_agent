from typing import Any

_WEIGHTS = {
    "intent_critical_technical": 0.30,
    "intent_technical": 0.15,
    "intent_bug": 0.08,
    "urgency_score": 0.20,
    "is_anomaly": 0.10,
    "sla_breached": 0.15,
}


class PriorityPredictor:
    name = "priority_predictor"

    async def run(self, ticket_data: dict, classification: dict, ml_signals: dict) -> dict[str, Any]:
        score = self._compute(ticket_data, classification, ml_signals)
        priority, confidence = self._map_score(score)

        ml_sev = ml_signals.get("severity", {})
        if ml_sev.get("level") == "critical" and ml_sev.get("confidence", 0) >= 0.85:
            priority = "critical"
            confidence = max(confidence, ml_sev["confidence"])

        if classification.get("urgency_score", 0) >= 0.9:
            priority = "critical"

        return {
            "predicted_priority": priority,
            "confidence": round(confidence, 3),
            "score": round(score, 3),
            "factors": self._explain(ticket_data, classification, ml_signals),
        }

    def _compute(self, ticket_data: dict, classification: dict, ml_signals: dict) -> float:
        s = 0.0
        intent = classification.get("intent", "")
        is_critical = classification.get("suggested_priority") == "critical"

        s += _WEIGHTS["intent_critical_technical"] * (intent in ("technical", "bug") and is_critical)
        s += _WEIGHTS["intent_technical"] * (intent == "technical")
        s += _WEIGHTS["intent_bug"] * (intent == "bug")
        s += _WEIGHTS["urgency_score"] * classification.get("urgency_score", 0)
        s += _WEIGHTS["is_anomaly"] * bool(ml_signals.get("is_anomaly"))
        s += _WEIGHTS["sla_breached"] * bool(ticket_data.get("response_sla_breached"))
        return min(1.0, s)

    @staticmethod
    def _map_score(score: float) -> tuple[str, float]:
        if score >= 0.65:
            return "critical", min(0.95, score)
        if score >= 0.40:
            return "high", min(0.90, score + 0.1)
        if score >= 0.20:
            return "medium", 0.75
        return "low", 0.80

    @staticmethod
    def _explain(ticket_data: dict, classification: dict, ml_signals: dict) -> list[str]:
        factors: list[str] = []
        intent = classification.get("intent", "")
        if intent in ("technical", "bug") and classification.get("suggested_priority") == "critical":
            factors.append(f"high-impact intent: {intent}")
        if classification.get("urgency_score", 0) >= 0.5:
            factors.append(f"urgency={classification['urgency_score']:.2f}")
        if ml_signals.get("is_anomaly"):
            factors.append("anomalous pattern")
        if ticket_data.get("response_sla_breached"):
            factors.append("SLA breached")
        sev = ml_signals.get("severity", {}).get("level")
        if sev in ("critical", "high"):
            factors.append(f"ML severity={sev}")
        return factors


priority_predictor = PriorityPredictor()

