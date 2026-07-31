"""Code node — run arbitrary Python code in a restricted namespace.

The code has access to:
  - `inputs` : dict of upstream outputs / external inputs
  - `config` : this node's config
It must set a variable `result` to a JSON-serialisable value, or define an
async `main()` coroutine returning the result.

Safety: executed with restricted builtins and no imports of os/subprocess by
default. This is NOT a sandbox — for untrusted code, run inside a container.
"""
from __future__ import annotations

import asyncio
import inspect
import json
import logging
from typing import Any, Dict

from ..registry import BaseNode, register_node

log = logging.getLogger("aita.nodes.code")

# a small safe builtins set
_SAFE_BUILTINS = {
    "abs": abs, "all": all, "any": any, "bool": bool, "dict": dict, "enumerate": enumerate,
    "filter": filter, "float": float, "hash": hash, "int": int, "isinstance": isinstance,
    "len": len, "list": list, "map": map, "max": max, "min": min, "print": print,
    "range": range, "round": round, "set": set, "sorted": sorted, "str": str,
    "sum": sum, "tuple": tuple, "zip": zip, "True": True, "False": False, "None": None,
    "open": open,  # file ops are useful; restrict at deploy time if needed
}


@register_node("code")
class CodeNode(BaseNode):
    """Run Python code. Returns whatever `result` is set to in the snippet."""

    async def run(self) -> Any:
        code = self.config.get("code", "")
        if not code.strip():
            raise ValueError("code is required")

        # pull named upstream outputs into the namespace
        inputs: Dict[str, Any] = {}
        for k, v in self.config.items():
            if k == "code":
                continue
            inputs[k] = v

        glob = {"__builtins__": _SAFE_BUILTINS, "inputs": inputs, "config": self.config, "json": json}
        loc: Dict[str, Any] = {}

        try:
            exec(compile(code, "<code-node>", "exec"), glob, loc)
        except Exception as e:
            raise RuntimeError(f"Code error: {e}") from e

        # prefer an async main(), then a sync main(), then a `result` var
        if "main" in loc:
            main = loc["main"]
            if inspect.iscoroutinefunction(main):
                return await main()
            if callable(main):
                return main()
        if "result" in loc:
            return loc["result"]
        raise ValueError("Code must define `result` or a `main()` function.")


    @classmethod
    def schema(cls):
        return {
            "type": "code",
            "label": "Python Code",
            "description": "Run a Python snippet. Define `result` or `main()`.",
            "color": "#16a34a",
            "fields": [
                {"name": "code", "type": "code", "language": "python", "required": True,
                 "default": "# available: inputs, config, json\n# set `result` or define main()\nresult = inputs"},
            ],
        }
