"""HTTP node — perform REST API requests."""
from __future__ import annotations

import json as _json
import logging
from typing import Any, Dict

import httpx

from ..registry import BaseNode, register_node

log = logging.getLogger("aita.nodes.http")


@register_node("http")
class HTTPNode(BaseNode):
    """Perform an HTTP request. Returns {"status": int, "headers": {}, "body": any, "url": str}."""

    async def run(self) -> Dict[str, Any]:
        method = self.config.get("method", "GET").upper()
        url = self.config.get("url", "")
        headers = self.config.get("headers", {}) or {}
        query = self.config.get("query", {}) or {}
        body = self.config.get("body", None)
        timeout = float(self.config.get("timeout", 30))

        if not url:
            raise ValueError("url is required")

        # body can be a dict (JSON) or a string
        json_body = None
        content = None
        if body is not None:
            if isinstance(body, (dict, list)):
                json_body = body
            else:
                content = str(body)

        async with httpx.AsyncClient(timeout=timeout) as client:
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
    def schema(cls):
        return {
            "type": "http",
            "label": "HTTP Request",
            "description": "Perform a REST API request.",
            "color": "#0ea5e9",
            "fields": [
                {"name": "method", "type": "select", "options": ["GET", "POST", "PUT", "PATCH", "DELETE"], "default": "GET"},
                {"name": "url", "type": "string", "required": True},
                {"name": "headers", "type": "object", "default": {}},
                {"name": "query", "type": "object", "default": {}},
                {"name": "body", "type": "any", "default": None},
                {"name": "timeout", "type": "number", "default": 30},
            ],
        }
