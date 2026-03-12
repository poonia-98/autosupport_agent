from plugins.base import AgentPlugin


class SignalAuditPlugin(AgentPlugin):
    name = "signal_audit"

    def run(self, ticket_data: dict, context: dict) -> dict:
        cls = context.get("classification", {})
        pri = context.get("priority", {})
        esc = context.get("escalation", {})

        intent_conf   = cls.get("intent_confidence", 0.0)
        priority_conf = pri.get("confidence", 0.0)
        esc_score     = esc.get("escalation_score", 0)

        overall = float(min(1.0, (intent_conf + priority_conf + (esc_score / 100)) / 3.0))

        flags: list[str] = []
        if intent_conf < 0.5:
            flags.append("low_intent_confidence")
        if priority_conf < 0.6:
            flags.append("uncertain_priority")
        if esc.get("escalation_level", 0) >= 2 and not esc.get("triggered_signals"):
            flags.append("unexplained_escalation")

        return {
            "overall_confidence": overall,
            "flags":              flags,
            "audit_passed":       len(flags) == 0,
        }


plugin = SignalAuditPlugin()
