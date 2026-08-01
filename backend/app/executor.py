"""DAG executor — production-grade.

A workflow is a directed acyclic graph (DAG) of nodes. Each node has:
  - id            : unique string id
  - type          : registered node type (e.g. "llm", "http", "code", ...)
  - config        : dict of static config for the node
  - inputs / outputs : ports (mostly cosmetic for the UI; execution uses id refs)

Nodes reference each other's outputs using templates in their config values,
e.g.  {{generate.title}}  resolves to the "title" key of the output dict
produced by the node whose id is "generate".

The executor:
  1. Validates the workflow (node count, cycle detection).
  2. Builds a dependency graph from template references.
  3. Topologically sorts it.
  4. Runs each node once its dependencies are done.
  5. Parallelises independent nodes with asyncio, capped by a semaphore.
  6. Applies a per-node timeout and optional retry.
  7. Propagates errors: if a dependency fails, downstream nodes are skipped.

Secrets are never stored in the workflow. A config value of
  ${{env:MY_KEY}}
is resolved from environment variables at execution time.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from .config import Settings, get_settings
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


def find_refs(value: Any) -> list[str]:
    """Return the set of node_ids this value (recursively) references."""
    deps: list[str] = []
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


def substitute(value: Any, outputs: dict[str, Any]) -> Any:
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
    status: str  # "success" | "error" | "skipped"
    output: Any = None
    error: str = ""
    started_at: float | None = None
    finished_at: float | None = None
    attempts: int = 1

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "output": self.output,
            "error": self.error,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(
                (self.finished_at or 0) - (self.started_at or 0), 3
            ) if self.started_at and self.finished_at else None,
            "attempts": self.attempts,
        }


@dataclass
class ExecutionResult:
    workflow_id: str
    status: str  # "success" | "error"
    nodes: dict[str, NodeResult] = field(default_factory=dict)
    started_at: float | None = None
    finished_at: float | None = None
    error: str = ""  # workflow-level error (e.g. cycle, no nodes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "workflow_id": self.workflow_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_s": round(
                (self.finished_at or time.time()) - (self.started_at or time.time()), 3
            ),
            "error": self.error,
            "nodes": {nid: nr.to_dict() for nid, nr in self.nodes.items()},
        }


# --- topological sort ------------------------------------------------------


def _topo_sort(nodes: list[dict]) -> list[str]:
    """Return node ids in execution order based on {{ref}} dependencies.

    Raises ValueError on cycles or self-references.
    """
    by_id = {n["id"]: n for n in nodes}
    deps: dict[str, set[str]] = {n["id"]: set() for n in nodes}
    for n in nodes:
        for d in find_refs(n.get("config", {})):
            if d == n["id"]:
                raise ValueError(f"Node '{n['id']}' references itself.")
            if d in by_id:
                deps[n["id"]].add(d)

    order: list[str] = []
    ready = sorted(nid for nid, d in deps.items() if not d)
    if not ready:
        raise ValueError(
            "Cycle detected (no node has zero dependencies) — workflow is not a DAG."
        )
    while ready:
        nid = ready.pop(0)
        order.append(nid)
        for other, d in deps.items():
            if nid in d:
                d.discard(nid)
                if not d and other not in order and other not in ready:
                    ready.append(other)
    if len(order) != len(nodes):
        remaining = set(by_id) - set(order)
        raise ValueError(f"Cycle detected — these nodes form a loop: {remaining}")
    return order


# --- executor --------------------------------------------------------------


class WorkflowExecutor:
    """Runs a workflow definition with production safeguards.

    Args:
        node_overrides: optional {node_type: callable} to inject custom node
            implementations (used for tests / sandboxing code nodes).
        settings: inject settings (tests); defaults to global singleton.
    """

    def __init__(
        self,
        node_overrides: dict[str, Callable[..., Awaitable[Any]]] | None = None,
        settings: Settings | None = None,
    ) -> None:
        self.overrides = node_overrides or {}
        self.settings = settings or get_settings()

    async def run(
        self, workflow: dict[str, Any], inputs: dict[str, Any] | None = None
    ) -> ExecutionResult:
        wf_id = workflow.get("id", "workflow")
        nodes = workflow.get("nodes", [])

        if not nodes:
            return ExecutionResult(
                workflow_id=wf_id, status="error",
                started_at=time.time(), finished_at=time.time(),
                error="No nodes in workflow.",
            )

        # Safety cap
        if len(nodes) > self.settings.max_workflow_nodes:
            return ExecutionResult(
                workflow_id=wf_id, status="error",
                started_at=time.time(), finished_at=time.time(),
                error=f"Workflow has {len(nodes)} nodes; max allowed is "
                      f"{self.settings.max_workflow_nodes}.",
            )

        result = ExecutionResult(
            workflow_id=wf_id, status="success", started_at=time.time()
        )
        outputs: dict[str, Any] = {}

        # Seed with external inputs, addressable as {{inputs.foo}}
        if inputs:
            outputs["inputs"] = inputs

        # Topological sort
        try:
            order = _topo_sort(nodes)
        except ValueError as e:
            result.status = "error"
            result.finished_at = time.time()
            result.error = str(e)
            return result

        # Concurrency semaphore — limits parallel node execution
        sem = asyncio.Semaphore(self.settings.max_concurrent_nodes)
        by_id = {n["id"]: n for n in nodes}
        done: set[str] = set()

        while len(done) < len(order):
            wave = [
                nid for nid in order
                if nid not in done
                and all(
                    d in done
                    for d in find_refs(by_id[nid].get("config", {}))
                    if d in by_id
                )
            ]
            if not wave:
                break

            tasks = [
                self._run_node(by_id[nid], outputs, result, sem)
                for nid in wave
            ]
            await asyncio.gather(*tasks)
            done.update(wave)

        result.finished_at = time.time()
        if any(nr.status == "error" for nr in result.nodes.values()):
            result.status = "error"
        return result

    async def _run_node(
        self,
        node: dict,
        outputs: dict[str, Any],
        result: ExecutionResult,
        sem: asyncio.Semaphore,
    ) -> None:
        """Run a single node with timeout, retry, and concurrency control."""
        nid = node["id"]
        ntype = node.get("type")
        config = node.get("config", {})

        # Check upstream errors — skip if a dependency failed
        deps = find_refs(config)
        for d in deps:
            if d in result.nodes and result.nodes[d].status == "error":
                nr = NodeResult(
                    node_id=nid, status="skipped",
                    error=f"Upstream node '{d}' failed; skipping.",
                    started_at=time.time(), finished_at=time.time(),
                )
                result.nodes[nid] = nr
                outputs[nid] = {"error": nr.error}
                return

        nr = NodeResult(node_id=nid, status="success", started_at=time.time())
        timeout = self.settings.default_node_timeout
        max_retries = 0  # extensible: per-node-type retry policy could go here

        async with sem:  # respect concurrency limit
            for attempt in range(1, max_retries + 2):
                nr.attempts = attempt
                try:
                    resolved_config = substitute(config, outputs)
                    node_cls = self.overrides.get(ntype) or get_node_class(ntype)
                    if node_cls is None:
                        raise ValueError(
                            f"Unknown node type '{ntype}'. "
                            f"Available: {list(NODE_TYPES.keys())}"
                        )
                    output = await asyncio.wait_for(
                        node_cls(resolved_config, context=outputs).run(),
                        timeout=timeout,
                    )
                    nr.output = output
                    outputs[nid] = output
                    nr.finished_at = time.time()
                    result.nodes[nid] = nr
                    return  # success

                except TimeoutError:
                    nr.status = "error"
                    nr.error = f"Node timed out after {timeout}s."
                    log.warning("Node %s timed out after %ss (attempt %d)",
                                nid, timeout, attempt)
                except Exception as e:
                    nr.status = "error"
                    nr.error = f"{type(e).__name__}: {e}"
                    log.exception("Node %s failed (attempt %d)", nid, attempt)

                if attempt <= max_retries:
                    await asyncio.sleep(0.5 * attempt)  # simple backoff

        nr.finished_at = time.time()
        result.nodes[nid] = nr
        outputs[nid] = {"error": nr.error}
