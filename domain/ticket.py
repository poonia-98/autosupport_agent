from core.exceptions import InvalidStateTransition

# explicit allowed transitions — anything not listed is rejected
_TRANSITIONS: dict[str, frozenset[str]] = {
    "open":         frozenset({"in_progress", "sla_breached", "escalated", "resolved", "closed"}),
    "in_progress":  frozenset({"resolved", "sla_breached", "escalated", "closed"}),
    "sla_breached": frozenset({"in_progress", "resolved", "closed"}),
    "escalated":    frozenset({"in_progress", "resolved", "closed"}),
    "resolved":     frozenset({"closed", "open"}),   # reopen is valid
    "closed":       frozenset(),
}


def validate_transition(from_status: str, to_status: str) -> None:
    """Raises InvalidStateTransition if the move is not permitted."""
    allowed = _TRANSITIONS.get(from_status, frozenset())
    if to_status not in allowed:
        raise InvalidStateTransition(from_status, to_status)


def can_transition(from_status: str, to_status: str) -> bool:
    return to_status in _TRANSITIONS.get(from_status, frozenset())
