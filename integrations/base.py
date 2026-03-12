from abc import ABC, abstractmethod
from typing import Any, Optional


class BaseIntegration(ABC):
    type_name: str = ""

    @abstractmethod
    def validate_config(self, config: dict[str, Any]) -> None:
        """Raise ValueError with a clear message if config is insufficient."""
        ...

    @abstractmethod
    async def test_connection(self, config: dict[str, Any], secret: Optional[str]) -> dict[str, Any]:
        """Return {"ok": bool, "message": str}. Must not raise."""
        ...

    @abstractmethod
    def parse_inbound(self, payload: dict[str, Any], secret: Optional[str]) -> Optional[dict[str, Any]]:
        """Normalise inbound payload to ticket dict. Return None to ignore."""
        ...
