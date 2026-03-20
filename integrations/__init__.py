from integrations.base import BaseIntegration
from integrations.webhook import WebhookIntegration, webhook_integration

_REGISTRY: dict[str, BaseIntegration] = {
    "webhook": webhook_integration,
}


def get_adapter(integration_type: str) -> BaseIntegration:
    adapter = _REGISTRY.get(integration_type)
    if not adapter:
        raise ValueError(f"Unknown integration type: {integration_type!r}. Supported: {list(_REGISTRY)}")
    return adapter


def supported_types() -> list[str]:
    return list(_REGISTRY)

