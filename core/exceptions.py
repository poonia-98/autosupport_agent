class AutoSupportError(Exception):
    pass

class TicketNotFound(AutoSupportError):
    def __init__(self, ticket_id: str):
        super().__init__(f"Ticket not found: {ticket_id}")

class InvalidTicketData(AutoSupportError):
    pass

class InvalidStateTransition(AutoSupportError):
    def __init__(self, from_status: str, to_status: str):
        super().__init__(f"Cannot transition ticket from {from_status!r} to {to_status!r}")

class AgentPipelineError(AutoSupportError):
    pass

class AuthenticationError(AutoSupportError):
    pass

class AuthorizationError(AutoSupportError):
    pass

class RateLimitExceeded(AutoSupportError):
    pass

class UserNotFound(AutoSupportError):
    def __init__(self, identifier: str):
        super().__init__(f"User not found: {identifier}")

class IntegrationError(AutoSupportError):
    pass
