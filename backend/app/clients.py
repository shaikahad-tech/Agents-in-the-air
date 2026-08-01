"""Client pools — reuse expensive clients (LLM SDK, httpx) across requests.

Creating a new ``AsyncOpenAI`` or ``AsyncAnthropic`` client per node execution
rebuilds connection pools every time. This module provides module-level singletons
keyed by API key, so connections are reused across workflow runs.

For ``httpx``, a shared ``AsyncClient`` with a connection pool is used so the
HTTP node doesn't pay the TLS handshake cost on every request.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("aita.clients")


# ─── LLM client pools ────────────────────────────────────────────────────

_openai_clients: dict[str, Any] = {}
_anthropic_clients: dict[str, Any] = {}
_gemini_configured: bool = False


def get_openai_client(api_key: str, timeout: float = 60.0):
    """Return a cached AsyncOpenAI client keyed by API key."""
    key = f"{api_key}:{timeout}"
    if key not in _openai_clients:
        from openai import AsyncOpenAI
        _openai_clients[key] = AsyncOpenAI(api_key=api_key, timeout=timeout)
        log.debug("Created new AsyncOpenAI client (pool size: %d)", len(_openai_clients))
    return _openai_clients[key]


def get_anthropic_client(api_key: str, timeout: float = 60.0):
    """Return a cached AsyncAnthropic client keyed by API key."""
    key = f"{api_key}:{timeout}"
    if key not in _anthropic_clients:
        import anthropic
        _anthropic_clients[key] = anthropic.AsyncAnthropic(api_key=api_key, timeout=timeout)
        log.debug("Created new AsyncAnthropic client (pool size: %d)", len(_anthropic_clients))
    return _anthropic_clients[key]


def configure_gemini(api_key: str) -> bool:
    """Configure Gemini SDK once. Returns True if (re)configured."""
    global _gemini_configured
    if not _gemini_configured:
        import google.generativeai as genai
        genai.configure(api_key=api_key)
        _gemini_configured = True
        log.debug("Configured Gemini SDK")
    return True


# ─── httpx shared client ─────────────────────────────────────────────────

_http_client: Any | None = None


async def get_http_client(timeout: float = 30.0, max_redirects: int = 5):
    """Return a shared httpx.AsyncClient with a connection pool.

    The client is created lazily on first use and reused across all HTTP
    node executions. This avoids the TLS handshake overhead on every request.
    """
    global _http_client
    if _http_client is None or _http_client.is_closed:
        import httpx
        _http_client = httpx.AsyncClient(
            timeout=timeout,
            max_redirects=max_redirects,
            follow_redirects=True,
            limits=httpx.Limits(
                max_connections=20,
                max_keepalive_connections=10,
                keepalive_expiry=30,
            ),
        )
        log.debug("Created shared httpx.AsyncClient with connection pool")
    return _http_client


async def close_all_clients() -> None:
    """Clean up all pooled clients. Called on app shutdown."""
    global _http_client, _gemini_configured
    if _http_client and not _http_client.is_closed:
        await _http_client.aclose()
        _http_client = None
    _openai_clients.clear()
    _anthropic_clients.clear()
    _gemini_configured = False
    log.info("All client pools cleared")
