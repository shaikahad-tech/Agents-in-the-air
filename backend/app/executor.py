"""DAG executor.

A workflow is a directed acyclic graph (DAG) of nodes. Each node has:
  - id            : unique string id
  - type          : registered node type (e.g. "llm", "http", "code", ...)
  - config        : dict of static config for the node
  - inputs / outputs : ports (mostly cosmetic for the UI; execution uses id refs)

Nodes reference each other's outputs using Jinja2-style templates in their
config values, e.g.  {{generate.title}}  resolves to the "title" key of the
output dict produced by the node whose id is "generate".

The executor:
  1. Builds a dependency graph from template references.
  2. Topologically sorts it.
  3. Runs each node once its dependencies are done.
  4. Parallelises independent nodes with asyncio.

Secrets are never stored in the workflow. A config value of
  ${{env:MY_KEY}}
is resolved from environment variables at execution time — the user wires the
real keys into the deployment env, not the graph.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Dict, List, Optional

from .registry import NODE_TYPES, get_node_class

log = logging.getLogger("aita.engine")

# --- template / reference parsing -----------------------------------------

# ${{env:VAR_NAME}}   -> environment variable lookup (secret)
_ENV_RE = re.compile(r"\$\{\{env:([A-Z0-9_]+)\}\}")
# {{node_id.field.subfield}} OR {{node_id}} -> reference to another node's output
_REF_RE = re.compile(r"\{\{\s*([a-zA-Z0-9_\-]+)(?:\.([a-zA-Z0-9_\.\-]*))?\s*\}\}")


def resolve_env(value: str) -> str:
    """Replace ${{env:NAME}} tokens with os.environ[NAME]."""
    def _sub(m: re.Match) -> str:
        name = m.group(1)
        if name not in os.environ:
            raise KeyError(
                f"Environment secret '{name}' is not set. "
                f"Add it to your deployment environment (see .env.example)."
            )
        return os.environ[name]
    return _ENV_RE.sub(_sub, value)


def find_refs(value: Any) -> List[str]:
    """Return the set of node_ids this value (recursively) references."""
    deps: List[str] = []
    if isinstance(value, str):
        for m in _REF_RE.finditer(value):
            deps.append(m.group(1))
        # env refs are not node deps
    elif isinstance(value, dict):
        for v in value.values():
            deps.extend(find_refs(v))
    elif isinstance(value, list):
        for v in value:
            deps.extend(find_refs(v))
    return deps


def substitute(value: Any, outputs: Dict[str, Any]) -> Any:
    """Recursively replace {{node.field}} tokens with concrete values."""
    if isinstance(value, str):
        # env first (secrets)
        value = resolve_env(value)

        # Fast path: if the entire string is a single ref, preserve native type.
        single = _REF_RE.fullmatch(value.strip())
        if single:
            node_id = single.group(1)
            path = single.group(2) or ""
            if node_id not in outputs:
                raise KeyError(f"Reference to unknown node '{node_id}'")
            cur: Any = outputs[node_id]
            if path:
                for part in path.split("."):
                    if isinstance(cur, dict):
                        cur = cur.get(part)
                    elif isinstance(cur, list) and part.isdigit():
                        cur = cur[int(part)]
                    else:
                        cur = getattr(cur, part, None)
            return cur

        # Slow path: string with embedded refs — coerce all to str.
        def _sub(m: re.Match) -> str:
            node_id = m.group(1)
            path = m.group(2) or ""
            if node_id not in outputs:
                raise KeyError(f"Reference to unknown node '{node_id}'")
            cur = outputs[node_id]
            if path:
                for part in path.split("."):
                    if isinstance(cur, dict):
                        cur = cur.get(part, "")
                    elif isinstance(cur, list) and part.isdigit():
                        cur = cur[int(part)] if int(part) < len(cur) else ""
                    else:
                        cur = getattr(cur, part, "")
            return str(cur) if not isinstance(cur, str) else cur

        return _REF_RE.sub(_sub, value)
    if isinstance(value, dict):
        return {k: substitute(v, outputs) for k, v in value.items()}
    if isinstance(value, list):
        return [substitute(v, outputs) for v in value]
    return value


# --- dataclasses -----------------------------------------------------------


@dataclass
class NodeResult:
    node_id: str
    status: str  # "success" | "error"
    output: Any = None
    error: str = ""
    started_at: Optional[float] = None
    finished_at: Optional[float] = None


@dataclass
class ExecutionResult:
    workflow_id: str
    status: str  # "success" | "error"
    nodes: Dict[str, NodeResult] = field(default_factory=dict)
    started_at: Optional[float] = None
    finished_at: Optional[float] = None

    def to_dict(self) -> Dict[str, Any]:
        import time as _time
        return {
            "workflow_id": self.workflow_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round((self.finished_at or _time.time()) - (self.started_at or _time.time()), 3),
            "nodes": {
                nid: {
                    "status": nr.status,
                    "output": nr.output,
                    "error": nr.error,
                }
                for nid, nr in self.nodes.items()
            },
        }


# --- topological sort ------------------------------------------------------


def _topo_sort(nodes: List[dict]) -> List[str]:
    """Return node ids in execution order based on {{ref}} dependencies."""
    by_id = {n["id"]: n for n in nodes}
    deps: Dict[str, set] = {n["id"]: set() for n in nodes}
    for n in nodes:
        for d in find_refs(n.get("config", {})):
            if d in by_id and d != n["id"]:
                deps[n["id"]].add(d)

    order: List[str] = []
    ready = [nid for nid, d in deps.items() if not d]
    if not ready:
        raise ValueError("Cycle detected (no node has zero dependencies) — workflow is not a DAG.")
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for other, d in deps.items():
            if nid in d:
                d.discard(nid)
                if not d and other not in order:
                    ready.append(other)
    if len(order) != len(nodes):
        remaining = set(by_id) - set(order)
        raise ValueError(f"Cycle detected — these nodes form a loop: {remaining}")
    return order


# --- executor --------------------------------------------------------------


class WorkflowExecutor:
    """Runs a workflow definition.

    Args:
        node_overrides: optional {node_type: callable} to inject custom node
            implementations (used for tests / sandboxing code nodes).
    """

    def __init__(
        self,
        node_overrides: Optional[Dict[str, Callable[..., Awaitable[Any]]]] = None,
    ) -> None:
        self.overrides = node_overrides or {}

    async def run(self, workflow: Dict[str, Any], inputs: Optional[Dict[str, Any]] = None) -> ExecutionResult:
        import time as _time
        wf_id = workflow.get("id", "workflow")
        nodes = workflow.get("nodes", [])
        if not nodes:
            return ExecutionResult(workflow_id=wf_id, status="error", error="No nodes in workflow.")

        result = ExecutionResult(workflow_id=wf_id, status="success", started_at=_time.time())
        outputs: Dict[str, Any] = {}

        # Seed with external inputs, addressable as {{inputs.foo}}
        if inputs:
            outputs["inputs"] = inputs

        try:
            order = _topo_sort(nodes)
        except ValueError as e:
            result.status = "error"
            result.finished_at = _time.time()
            result.error = str(e)
            return result

        # group into "waves" of independent nodes for parallel execution
        by_id = {n["id"]: n for n in nodes}
        done: set = set()
        while len(done) < len(order):
            wave = [
                nid for nid in order
                if nid not in done
                and all(d in done for d in find_refs(by_id[nid].get("config", {})) if d in by_id)
            ]
            if not wave:
                break

            tasks = [self._run_node(by_id[nid], outputs, result) for nid in wave]
            await asyncio.gather(*tasks)
            done.update(wave)

        result.finished_at = _time.time()
        if any(nr.status == "error" for nr in result.nodes.values()):
            result.status = "error"
        return result

    async def _run_node(self, node: dict, outputs: Dict[str, Any], result: ExecutionResult) -> None:
        import time as _time
        nid = node["id"]
        ntype = node.get("type")
        config = node.get("config", {})

        # check upstream errors — if a dependency errored, skip
        deps = find_refs(config)
        for d in deps:
            if d in result.nodes and result.nodes[d].status == "error":
                nr = NodeResult(
                    node_id=nid, status="error",
                    error=f"Upstream node '{d}' failed; skipping.",
                    started_at=_time.time(), finished_at=_time.time(),
                )
                result.nodes[nid] = nr
                outputs[nid] = {"error": nr.error}
                return

        nr = NodeResult(node_id=nid, status="success", started_at=_time.time())
        try:
            resolved_config = substitute(config, outputs)
            node_cls = self.overrides.get(ntype) or get_node_class(ntype)
            if node_cls is None:
                raise ValueError(f"Unknown node type '{ntype}'. Available: {list(NODE_TYPES.keys())}")
            output = await node_cls(resolved_config, context=outputs).run()
            nr.output = output
            outputs[nid] = output
        except Exception as e:
            log.exception("Node %s failed", nid)
            nr.status = "error"
            nr.error = f"{type(e).__name__}: {e}"
            outputs[nid] = {"error": str(e)}
        nr.finished_at = _time.time()
        result.nodes[nid] = nr
