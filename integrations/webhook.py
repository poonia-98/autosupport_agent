import hmac
import hashlib
import json
import logging
from typing import Any, Optional

import httpx

from integrations.base import BaseIntegration

logger = logging.getLogger("integration.webhook")


class WebhookIntegration(BaseIntegration):
    type_name = "webhook"

    def validate_config(self, config: dict[str, Any]) -> None:
        # notify_url is optional; no required fields for inbound-only usage
        pass

    async def test_connection(self, config: dict[str, Any], secret: Optional[str]) -> dict[str, Any]:
        notify_url = config.get("notify_url", "").strip()
        if not notify_url:
            return {"ok": True, "message": "Webhook ready. No outbound notify_url configured."}
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(notify_url, json={"event": "ping", "source": "autosupport"})
            if r.status_code < 500:
                return {"ok": True, "message": f"Ping delivered — HTTP {r.status_code}"}
            return {"ok": False, "message": f"Endpoint returned HTTP {r.status_code}"}
        except Exception as exc:
            return {"ok": False, "message": str(exc)}

    def parse_inbound(self, payload: dict[str, Any], secret: Optional[str]) -> Optional[dict[str, Any]]:
        if payload.get("event") in ("ping", "health_check", "test"):
            return None

        title = (payload.get("title") or payload.get("subject") or "").strip()
        if not title:
            return None

        priority = payload.get("priority", "medium")
        if priority not in ("low", "medium", "high", "critical"):
            priority = "medium"

        category = payload.get("category", "general")
        if category not in ("billing", "technical", "bug", "feature_request", "general"):
            category = "general"

        return {
            "title":           title[:255],
            "description":     str(payload.get("description") or payload.get("body") or "")[:4000],
            "priority":        priority,
            "category":        category,
            "source":          "webhook",
            "integration_ref": str(payload.get("source_id") or payload.get("id") or "")[:64],
        }

    async def send_notification(
        self,
        notify_url: str,
        event: str,
        ticket: dict[str, Any],
        secret: Optional[str] = None,
    ) -> bool:
        body = {
            "event":     event,
            "ticket_id": ticket.get("id"),
            "title":     ticket.get("title"),
            "priority":  ticket.get("priority"),
            "status":    ticket.get("status"),
            "team":      ticket.get("assigned_team"),
        }
        headers = {"Content-Type": "application/json"}
        if secret:
            raw = json.dumps(body, separators=(",", ":")).encode()
            sig = "sha256=" + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
            headers["X-AutoSupport-Signature"] = sig
        try:
            async with httpx.AsyncClient(timeout=5) as client:
                r = await client.post(notify_url, json=body, headers=headers)
            return r.status_code < 400
        except Exception as exc:
            logger.warning("webhook.send_notification.failed", extra={"url": notify_url, "error": str(exc)})
            return False


webhook_integration = WebhookIntegration()
