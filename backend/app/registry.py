"""Node registry and base class."""
from __future__ import annotations

from typing import Any, Dict, Optional, Type
import logging

log = logging.getLogger("aita.registry")

NODE_TYPES: Dict[str, Type["BaseNode"]] = {}


def register_node(name: str):
    """Class decorator: register a node implementation under `name`."""
    def deco(cls: Type["BaseNode"]) -> Type["BaseNode"]:
        NODE_TYPES[name] = cls
        cls.type_name = name
        return cls
    return deco


def get_node_class(name: str) -> Optional[Type["BaseNode"]]:
    return NODE_TYPES.get(name)


def available_node_types() -> list:
    return [
        {"type": t, "schema": cls.schema()}
        for t, cls in sorted(NODE_TYPES.items())
    ]


class BaseNode:
    """Base class for all node implementations.

    A node receives its resolved config (templates already substituted) and a
    `context` dict holding all upstream node outputs + external inputs.
    """

    type_name: str = "base"

    def __init__(self, config: Dict[str, Any], context: Optional[Dict[str, Any]] = None) -> None:
        self.config = config
        self.context = context or {}

    async def run(self) -> Any:
        raise NotImplementedError

    @classmethod
    def schema(cls) -> Dict[str, Any]:
        """Return a JSON-schema-ish description for the UI config panel."""
        return {
            "type": cls.type_name,
            "label": cls.type_name.title(),
            "description": getattr(cls, "__doc__", "") or "",
            "fields": [],
        }
