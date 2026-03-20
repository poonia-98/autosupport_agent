from abc import ABC, abstractmethod
from typing import Any


class AgentPlugin(ABC):
    name: str = ""

    @abstractmethod
    def run(self, ticket_data: dict, context: dict) -> Any: ...

