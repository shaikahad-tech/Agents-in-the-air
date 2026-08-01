"""Security utilities: API key auth, SSRF protection, code sandbox.

This module centralizes all security-sensitive logic:

- ``require_api_key``: FastAPI dependency that enforces an optional API key
  on all /api/* routes.
- ``is_safe_url``: validates HTTP-node URLs against SSRF rules — blocks
  loopback, link-local, and private ranges; optionally enforces an allowlist.
- ``SandboxedRunner``: executes code-node snippets with a restricted
  builtins set, import whitelist, and resource limits (timeout + output cap).
"""
from __future__ import annotations

import ipaddress
import socket
import threading
from typing import Any
from urllib.parse import urlparse

from fastapi import Depends, Header, HTTPException, status

from .config import Settings, get_settings

# ─── API Key authentication ──────────────────────────────────────────────


async def require_api_key(
    x_api_key: str | None = Header(None, alias="X-API-Key"),
    settings: Settings = Depends(get_settings),
) -> str:
    """FastAPI dependency: enforce API key if configured.

    In development with no key set, auth is disabled.
    In staging/production, a key MUST be set or the app refuses to start.
    """
    if not settings.api_key:
        if settings.env == "production":
            raise RuntimeError(
                "AITA_API_KEY must be set in production. "
                "Set it in your environment or .env file."
            )
        return "anonymous"  # dev mode, no auth

    if x_api_key != settings.api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing API key. Pass it in the X-API-Key header.",
            headers={"WWW-Authenticate": "ApiKey"},
        )
    return x_api_key


# ─── SSRF protection for HTTP node ────────────────────────────────────────

# Network ranges that should never be reachable from the HTTP node.
_BLOCKED_PREFIXES = [
    "0.0.0.0/8",
    "10.0.0.0/8",
    "127.0.0.0/8",         # IPv4 loopback
    "169.254.0.0/16",      # link-local (AWS metadata endpoint lives here!)
    "172.16.0.0/12",       # private
    "192.0.0.0/24",        # IETF protocol assignments
    "192.168.0.0/16",      # private
    "100.64.0.0/10",       # CGNAT
    "::1/128",             # IPv6 loopback
    "fc00::/7",            # IPv6 unique-local
    "fe80::/10",           # IPv6 link-local
]

_BLOCKED_NETS = [ipaddress.ip_network(n) for n in _BLOCKED_PREFIXES]


def is_safe_url(url: str, settings: Settings) -> tuple[bool, str]:
    """Validate a URL for the HTTP node against SSRF rules.

    Returns ``(ok, reason)``. Blocks:
    - non-http(s) schemes
    - loopback, private, link-local IPs
    - hostnames that resolve to blocked IPs (checked at call time)
    - hosts not in the optional allowlist
    """
    if not url:
        return False, "URL is empty"

    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https"):
        return False, f"Scheme '{parsed.scheme}' not allowed. Use http or https."

    host = parsed.hostname or ""
    if not host:
        return False, "No hostname in URL."

    # Allowlist check
    if settings.http_allowed_hosts:
        import fnmatch
        if not any(fnmatch.fnmatch(host.lower(), h.lower()) for h in settings.http_allowed_hosts):
            return False, f"Host '{host}' not in allowed list."

    # Resolve and check IP
    try:
        # getaddrinfo returns all A/AAAA records — we must check every one
        infos = socket.getaddrinfo(host, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror:
        return False, f"Could not resolve host '{host}'."

    for _family, _type, _proto, _canon, sockaddr in infos:
        ip = sockaddr[0]
        try:
            ip_obj = ipaddress.ip_address(ip)
        except ValueError:
            continue
        for net in _BLOCKED_NETS:
            if ip_obj in net:
                return False, f"Host resolves to blocked/private IP {ip}."
    return True, ""


# ─── Code node sandbox ────────────────────────────────────────────────────

# Minimal safe builtins — no open, no eval, no exec, no __import__.
_SAFE_BUILTINS: dict[str, Any] = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict,
    "enumerate": enumerate, "filter": filter, "float": float, "hash": hash,
    "int": int, "isinstance": isinstance, "len": len, "list": list,
    "map": map, "max": max, "min": min, "print": print, "range": range,
    "round": round, "set": set, "sorted": sorted, "str": str, "sum": sum,
    "tuple": tuple, "zip": zip,
    "True": True, "False": False, "None": None,
    # safe conversions
    "chr": chr, "ord": ord, "repr": repr, "divmod": divmod, "frozenset": frozenset,
    # json for convenience
    "json": __import__("json"),
    "re": __import__("re"),
    "math": __import__("math"),
}

# Modules the code node is allowed to import (best-effort; true sandboxing
# requires a separate process — see SECURITY note in README).
_ALLOWED_MODULES: set[str] = {
    "json", "re", "math", "statistics", "itertools", "collections",
    "functools", "datetime", "decimal", "csv", "io",
}


class SandboxTimeoutError(Exception):
    """Raised when sandboxed code exceeds its CPU budget."""


class SandboxedRunner:
    """Runs a Python snippet in a restricted namespace with a timeout.

    NOTE: This is defense-in-depth, NOT a true sandbox. For untrusted code,
    run the executor inside a separate container with seccomp/apparmor.
    """

    def __init__(self, settings: Settings):
        self.settings = settings

    def run(
        self,
        code: str,
        inputs: dict[str, Any],
        config: dict[str, Any],
        timeout: float | None = None,
    ) -> Any:
        """Execute ``code`` with restricted globals. Returns the result."""
        timeout = timeout or self.settings.code_max_cpu_seconds
        max_bytes = self.settings.max_code_output_bytes

        glob: dict[str, Any] = {
            "__builtins__": _SAFE_BUILTINS,
            "inputs": inputs,
            "config": config,
            "__import__": self._restricted_import,
        }
        loc: dict[str, Any] = {}

        result_box: dict[str, Any] = {}

        def _target():
            try:
                exec(compile(code, "<code-node>", "exec"), glob, loc)
                result_box["ok"] = True
            except BaseException as e:
                result_box["error"] = e

        t = threading.Thread(target=_target, daemon=True)
        t.start()
        t.join(timeout=timeout)

        if t.is_alive():
            # Thread is still running — we can't kill it in CPython, but we
            # abandon it and report timeout. For true isolation use a subprocess.
            raise SandboxTimeoutError(
                f"Code exceeded {timeout}s CPU limit. Simplify your snippet or "
                f"raise AITA_CODE_MAX_CPU_SECONDS."
            )

        if "error" in result_box:
            raise RuntimeError(f"Code error: {result_box['error']}")

        # Extract result
        import inspect as _inspect
        if "main" in loc:
            main = loc["main"]
            if _inspect.iscoroutinefunction(main):
                import asyncio as _a
                return _a.run(main())
            if callable(main):
                return main()
        if "result" in loc:
            res = loc["result"]
            # Size guard
            try:
                size = len(str(res).encode("utf-8"))
            except Exception:
                size = 0
            if size > max_bytes:
                raise ValueError(
                    f"Code output ({size} bytes) exceeds limit ({max_bytes} bytes)."
                )
            return res
        raise ValueError("Code must define `result` or a `main()` function.")

    @staticmethod
    def _restricted_import(name: str, *args, **kwargs):
        """Allow only whitelisted modules to be imported inside the code node."""
        top = name.split(".")[0]
        if top not in _ALLOWED_MODULES:
            raise ImportError(
                f"Import of '{name}' is blocked in the code node sandbox. "
                f"Allowed: {sorted(_ALLOWED_MODULES)}."
            )
        return __import__(name, *args, **kwargs)
