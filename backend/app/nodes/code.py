"""Code node — run Python code in a restricted namespace.

Uses ``SandboxedRunner`` from ``app.security`` which provides:
  - A minimal safe builtins set (no ``open``, ``eval``, ``exec``, ``__import__``)
  - An import whitelist (json, re, math, statistics, itertools, collections, ...)
  - A CPU timeout (default 30s)
  - An output size cap (default 1 MB)

NOTE: This is defense-in-depth, NOT a true security sandbox. For untrusted
workflows, run the executor inside a separate container with seccomp/apparmor.
"""
from __future__ import annotations

import logging
from typing import Any

from ..config import get_settings
from ..registry import BaseNode, register_node
from ..security import SandboxedRunner

log = logging.getLogger("aita.nodes.code")


@register_node("code")
class CodeNode(BaseNode):
    """Run Python code. Returns whatever `result` is set to in the snippet."""

    async def run(self) -> Any:
        settings = get_settings()
        code = self.config.get("code", "")
        if not code.strip():
            raise ValueError("code is required")

        # pull named upstream outputs into the namespace
        inputs: dict[str, Any] = {}
        for k, v in self.config.items():
            if k == "code":
                continue
            inputs[k] = v

        runner = SandboxedRunner(settings)
        return runner.run(code, inputs, self.config)

    @classmethod
    def schema(cls) -> dict[str, Any]:
        return {
            "type": "code",
            "label": "Python Code",
            "description": "Run a Python snippet in a restricted sandbox. "
                           "Define `result` or `main()`. No file/network access.",
            "color": "16a34a",
            "fields": [
                {"name": "code", "type": "code", "language": "python",
                 "required": True,
                 "default": "# available: inputs, config, json, re, math\n"
                            "# set `result` or define main()\n"
                            "result = inputs"},
            ],
        }
