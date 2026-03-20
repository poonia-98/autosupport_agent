import asyncio
import hashlib
import json
import time
from typing import Any

import httpx

from core.config import get_settings
from core.logging import get_logger

logger = get_logger("intelligence.llm")

_cache: dict[str, tuple[dict[str, Any], float]] = {}
_lock = asyncio.Lock()

_SYSTEM_PROMPT = (
    "You are a support ticket classifier. "
    "Respond ONLY with a JSON object: "
    '{"category": "<billing|technical|bug|feature_request|general>", '
    '"priority": "<low|medium|high|critical>", '
    '"should_escalate": <true|false>, '
    '"confidence": <0.0-1.0>}. '
    "Rules: critical=production outage/data loss/security breach; "
    "billing=payment/invoice/subscription; technical=login/api/integration/access; "
    "bug=something worked before now broken; feature_request=asking for new functionality. "
    "No markdown. No explanation. Valid JSON only."
)


def _cache_key(title: str, description: str) -> str:
    content = f"{title.strip().lower()}|{description.strip().lower()[:200]}"
    return hashlib.sha256(content.encode()).hexdigest()[:20]


async def classify(ticket_id: str, title: str, description: str) -> dict[str, Any] | None:
    settings = get_settings()
    if not settings.llm_enabled or not settings.llm_api_key:
        return None

    key = _cache_key(title, description)

    async with _lock:
        cached = _cache.get(key)
        if cached and cached[1] > time.time():
            logger.debug("llm.cache_hit", ticket_id=ticket_id)
            return cached[0]

    user_content = f"Title: {title}\nDescription: {(description or '').strip()[:800]}"

    try:
        async with httpx.AsyncClient(timeout=settings.llm_timeout) as client:
            r = await client.post(
                f"{settings.llm_base_url.rstrip('/')}/chat/completions",
                headers={
                    "Authorization": f"Bearer {settings.llm_api_key}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": settings.llm_model,
                    "messages": [
                        {"role": "system", "content": _SYSTEM_PROMPT},
                        {"role": "user", "content": user_content},
                    ],
                    "max_tokens": 100,
                    "temperature": 0.1,
                },
            )
            r.raise_for_status()
    except httpx.TimeoutException:
        logger.warning("llm.timeout", ticket_id=ticket_id)
        return None
    except httpx.HTTPStatusError as exc:
        logger.warning("llm.http_error", ticket_id=ticket_id, status=exc.response.status_code)
        return None
    except Exception as exc:
        logger.warning("llm.error", ticket_id=ticket_id, error=str(exc))
        return None

    try:
        text = r.json()["choices"][0]["message"]["content"].strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1].lstrip("json").strip() if len(parts) > 1 else text
        data = json.loads(text)
        result: dict[str, Any] = {
            "category": str(data.get("category", "general")),
            "priority": str(data.get("priority", "medium")),
            "should_escalate": bool(data.get("should_escalate", False)),
            "confidence": float(min(1.0, max(0.0, data.get("confidence", 0.7)))),
        }
    except (KeyError, ValueError, TypeError, json.JSONDecodeError) as exc:
        logger.warning("llm.parse_error", ticket_id=ticket_id, error=str(exc))
        return None

    async with _lock:
        _cache[key] = (result, time.time() + settings.llm_cache_ttl)
        # evict expired entries when cache grows
        if len(_cache) > 1000:
            now = time.time()
            expired = [k for k, (_, exp) in _cache.items() if exp <= now]
            for k in expired:
                del _cache[k]

    logger.info("llm.classified", ticket_id=ticket_id, category=result["category"])
    return result

