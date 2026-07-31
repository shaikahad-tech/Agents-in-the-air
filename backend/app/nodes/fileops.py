"""File operations node — read / write / list files.

Paths are resolved against a configurable workspace root (default /tmp/aita).
This keeps file nodes scoped to a workspace and prevents walking the FS.
"""
from __future__ import annotations

import json as _json
import os
import csv
import io
import logging
from typing import Any, Dict

from ..registry import BaseNode, register_node

log = logging.getLogger("aita.nodes.fileops")

DEFAULT_ROOT = os.environ.get("AITA_WORKSPACE", "/tmp/aita")


def _safe_path(root: str, p: str) -> str:
    rp = os.path.realpath(os.path.join(root, p))
    if not rp.startswith(os.path.realpath(root)):
        raise ValueError(f"Path escapes workspace root: {p}")
    return rp


@register_node("file")
class FileNode(BaseNode):
    """Read, write, or list files. Returns dict depending on operation."""

    async def run(self) -> Dict[str, Any]:
        op = self.config.get("operation", "read")
        path = self.config.get("path", "")
        content = self.config.get("content", "")
        root = self.config.get("root", DEFAULT_ROOT)
        os.makedirs(root, exist_ok=True)

        if op == "read":
            p = _safe_path(root, path)
            with open(p, "r", encoding="utf-8") as f:
                raw = f.read()
            # auto-parse JSON / CSV
            if path.endswith(".json"):
                return {"path": path, "content": _json.loads(raw)}
            if path.endswith((".csv", ".tsv")):
                delim = "\t" if path.endswith(".tsv") else ","
                reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
                return {"path": path, "rows": list(reader)}
            return {"path": path, "content": raw}

        if op == "write":
            p = _safe_path(root, path)
            os.makedirs(os.path.dirname(p), exist_ok=True)
            data = content
            if isinstance(data, (dict, list)):
                data = _json.dumps(data, indent=2, default=str)
            with open(p, "w", encoding="utf-8") as f:
                f.write(str(data))
            return {"path": path, "bytes": len(str(data)), "status": "written"}

        if op == "list":
            p = _safe_path(root, path)
            entries = []
            for name in sorted(os.listdir(p)):
                fp = os.path.join(p, name)
                entries.append({
                    "name": name,
                    "type": "dir" if os.path.isdir(fp) else "file",
                    "size": os.path.getsize(fp) if os.path.isfile(fp) else 0,
                })
            return {"path": path, "entries": entries}

        if op == "delete":
            p = _safe_path(root, path)
            if os.path.isdir(p):
                import shutil
                shutil.rmtree(p)
            else:
                os.remove(p)
            return {"path": path, "status": "deleted"}

        raise ValueError(f"Unknown file operation '{op}'. Use read|write|list|delete.")

    @classmethod
    def schema(cls):
        return {
            "type": "file",
            "label": "File",
            "description": "Read, write, list, or delete files in the workspace.",
            "color": "#f59e0b",
            "fields": [
                {"name": "operation", "type": "select", "options": ["read", "write", "list", "delete"], "default": "read"},
                {"name": "path", "type": "string", "required": True},
                {"name": "content", "type": "textarea", "default": ""},
                {"name": "root", "type": "string", "default": ""},
            ],
        }
