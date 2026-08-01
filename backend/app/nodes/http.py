"""HTTP node — perform REST API requests with SSRF protection.

Uses a shared ``httpx.AsyncClient`` from ``app.clients`` so connections
are pooled and reused across node executions — no TLS handshake per request.
"""
from __future__ import annotations

import logging
from typing import Any

from ..clients import get_http_client
from ..config import get_settings
from ..registry import BaseNode, register_node
from ..security import is_safe_url

log = logging.getLogger("aita.nodes.http")


@register_node("http")
class HTTPNode(BaseNode):
    """Perform an HTTP request. Returns
    {"status": int, "headers": {}, "body": any, "url": str}.
    """

    async def run(self) -> dict[str, Any]:
        settings = get_settings()
        method = self.config.get("method", "GET").upper()
        url = self.config.get("url", "")
        headers = self.config.get("headers", {}) or {}
        query = self.config.get("query", {}) or {}
        body = self.config.get("body", None)
        timeout = float(self.config.get("timeout", settings.http_default_timeout))

        if not url:
            raise ValueError("url is required")

        # SSRF check — block private/internal IPs
        ok, reason = is_safe_url(url, settings)
        if not ok:
            raise ValueError(f"URL rejected (SSRF protection): {reason}")

        # body can be a dict (JSON) or a string
        json_body = None
        content = None
        if body is not None:
            if isinstance(body, (dict, list)):
                json_body = body
            else:
                content = str(body)

        # Use shared client from pool — avoids per-request TLS handshake
        client = await get_http_client(timeout=timeout)
        resp = await client.request(
            method, url, headers=headers, params=query,
            json=json_body, content=content,
        )

        # try to parse JSON, else fall back to text
        try:
            parsed = resp.json()
        except Exception:
            parsed = resp.text

        return {
            "status": resp.status_code,
            "headers": dict(resp.headers),
            "body": parsed,
            "url": str(resp.url),
        }

    @classmethod
    def schema(cls) -> dict[str, Any]:
        return {
            "type": "http",
            "label": "HTTP Request",
            "description": "Perform a REST API request (SSRF-protected).",
            "color": "0ea5e9",
            "fields": [
                {"name": "method", "type": "select",
                 "options": ["GET", "POST", "PUT", "PATCH", "DELETE"],
                 "default": "GET"},
                {"name": "url", "type": "string", "required": True},
                {"name": "headers", "type": "object", "default": {}},
                {"name": "query", "type": "object", "default": {}},
                {"name": "body", "type": "any", "default": None},
                {"name": "timeout", "type": "number", "default": 30},
            ],
        }
