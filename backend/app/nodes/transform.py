"""Transform node — data reshaping utilities (no code execution).

Provides common data transforms so users don't need a code node for simple
operations: map, filter, extract, flatten, to_csv, from_csv, json_path.
"""
from __future__ import annotations

import csv
import io
import logging
from typing import Any

from ..registry import BaseNode, register_node

log = logging.getLogger("aita.nodes.transform")


@register_node("transform")
class TransformNode(BaseNode):
    """Apply a built-in data transform. Returns the transformed data."""

    async def run(self) -> Any:
        op = self.config.get("operation", "identity")
        data = self.config.get("data")
        field = self.config.get("field", "")
        expr = self.config.get("expr", "")

        if op == "identity":
            return data

        if op == "extract":
            # drill into nested dict/list by dotted path
            cur: Any = data
            for part in field.split("."):
                if isinstance(cur, list):
                    cur = [c.get(part) if isinstance(c, dict) else getattr(c, part, None) for c in cur]
                elif isinstance(cur, dict):
                    cur = cur.get(part)
                else:
                    cur = getattr(cur, part, None)
            return cur

        if op == "map":
            # data is a list of dicts; return list of values for `field`
            if not isinstance(data, list):
                raise ValueError("map expects a list")
            return [d.get(field) if isinstance(d, dict) else getattr(d, field, None) for d in data]

        if op == "filter":
            if not isinstance(data, list):
                raise ValueError("filter expects a list")
            # expr like "key==value" or "key>=10"
            return [d for d in data if _eval_filter(d, expr)]

        if op == "flatten":
            if not isinstance(data, list):
                raise ValueError("flatten expects a list of lists")
            return [item for sub in data for item in (sub if isinstance(sub, list) else [sub])]

        if op == "to_csv":
            if not isinstance(data, list):
                raise ValueError("to_csv expects a list of dicts")
            buf = io.StringIO()
            if data:
                w = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
                w.writeheader()
                w.writerows(data)
            return buf.getvalue()

        if op == "from_csv":
            if not isinstance(data, str):
                raise ValueError("from_csv expects a string")
            reader = csv.DictReader(io.StringIO(data))
            return list(reader)

        if op == "json_path":
            # very small JSON-path: a.b.0.c
            cur = data
            for part in field.split("."):
                if part.isdigit():
                    cur = cur[int(part)] if isinstance(cur, list) else None
                else:
                    cur = cur.get(part) if isinstance(cur, dict) else None
            return cur

        if op == "template":
            # string template with {field} placeholders against data dict
            if not isinstance(data, dict):
                raise ValueError("template expects data to be a dict")
            try:
                return expr.format(**data)
            except KeyError as e:
                raise ValueError(f"Missing key in template: {e}") from e

        raise ValueError(f"Unknown transform operation '{op}'")

    @classmethod
    def schema(cls):
        return {
            "type": "transform",
            "label": "Transform",
            "description": "Reshape data without code: extract, map, filter, flatten, CSV, JSON-path, template.",
            "color": "ec4899",
            "fields": [
                {"name": "operation", "type": "select",
                 "options": ["identity", "extract", "map", "filter", "flatten", "to_csv", "from_csv", "json_path", "template"],
                 "default": "identity"},
                {"name": "data", "type": "any", "default": None},
                {"name": "field", "type": "string", "default": ""},
                {"name": "expr", "type": "string", "default": ""},
            ],
        }


def _eval_filter(item, expr: str) -> bool:
    """Evaluate a simple filter expression like 'price>=100' or 'status==active'."""
    for op in [">=", "<=", "==", "!=", ">", "<"]:
        if op in expr:
            k, v = expr.split(op, 1)
            k = k.strip()
            v = v.strip()
            # try numeric
            try:
                v_num = float(v)
                iv = float(item.get(k, 0) if isinstance(item, dict) else getattr(item, k, 0))
                if op == ">=": return iv >= v_num
                if op == "<=": return iv <= v_num
                if op == "==": return iv == v_num
                if op == "!=": return iv != v_num
                if op == ">":  return iv > v_num
                if op == "<":  return iv < v_num
            except ValueError:
                iv = str(item.get(k, "") if isinstance(item, dict) else getattr(item, k, ""))
                if op == "==": return iv == v
                if op == "!=": return iv != v
    return False
