"""FastAPI app: workflow CRUD, node schemas, run endpoint, static UI.

Production improvements over the original:
  - Centralized settings via ``get_settings()``
  - Configurable CORS (not wildcard by default in prod)
  - API key authentication on all /api/* routes
  - Rate limiting + structured request logging middleware
  - Global exception handler (no traceback leakage in prod)
  - Pagination on list endpoints
  - Input validation with Pydantic v2
  - Workflow storage abstraction (JSON file now; DB-ready interface)
"""
from __future__ import annotations

import json
import logging
import uuid
from pathlib import Path
from typing import Any

from fastapi import Body, Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from . import nodes  # noqa: F401  — registers node types
from .config import Settings, get_settings
from .executor import WorkflowExecutor
from .middleware import (
    RateLimitMiddleware,
    RequestLoggingMiddleware,
    global_exception_handler,
)
from .registry import available_node_types
from .security import require_api_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
log = logging.getLogger("aita.api")


# ─── Models (module-level for Pydantic forward-ref resolution) ───────────


class NodeModel(BaseModel):
    id: str
    type: str
    config: dict[str, Any] = Field(default_factory=dict)
    position: dict[str, float] | None = None
    data: dict[str, Any] | None = None


class EdgeModel(BaseModel):
    id: str | None = None
    source: str
    target: str
    sourceHandle: str | None = None
    targetHandle: str | None = None


class WorkflowModel(BaseModel):
    id: str | None = None
    name: str = Field(..., min_length=1, max_length=200)
    description: str = ""
    nodes: list[NodeModel] = []
    edges: list[EdgeModel] = []


class RunRequest(BaseModel):
    workflow: WorkflowModel
    inputs: dict[str, Any] = Field(default_factory=dict)


class ListResponse(BaseModel):
    workflows: list[dict[str, Any]]
    total: int
    page: int
    page_size: int


# ─── App factory ─────────────────────────────────────────────────────────


def create_app(settings: Settings | None = None) -> FastAPI:
    """Application factory — allows tests to inject custom settings."""
    settings = settings or get_settings()
    settings.ensure_dirs()

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Drag-and-drop agentic workflow builder.",
        # Hide docs in production for security surface reduction
        docs_url=None if settings.env == "production" else "/docs",
        redoc_url=None if settings.env == "production" else "/redoc",
    )

    # ─── Middleware ───────────────────────────────────────────────────
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_methods=["GET", "POST", "PUT", "DELETE"],
        allow_headers=["*"],
        allow_credentials=False,
    )
    app.add_middleware(RateLimitMiddleware, settings=settings)
    app.add_middleware(RequestLoggingMiddleware, settings=settings)

    # ─── Global exception handler ────────────────────────────────────
    app.add_exception_handler(Exception, global_exception_handler)

    # ─── Lifecycle: close client pools on shutdown ───────────────────
    from contextlib import asynccontextmanager

    from .clients import close_all_clients

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        log.info("Application starting up (%s)", settings.env)
        yield
        await close_all_clients()
        log.info("Application shut down — client pools closed")

    app.router.lifespan_context = lifespan

    # ─── Storage ──────────────────────────────────────────────────────
    store = WorkflowStore(settings.data_dir)

    # ─── Executor ─────────────────────────────────────────────────────
    executor = WorkflowExecutor(settings=settings)

    # ─── Routes ───────────────────────────────────────────────────────

    @app.get("/api/health")
    async def health(_user: str = Depends(require_api_key)):
        return {
            "status": "ok",
            "version": settings.app_version,
            "env": settings.env,
            "node_types": [t["type"] for t in available_node_types()],
        }

    @app.get("/api/nodes")
    async def list_node_types(_user: str = Depends(require_api_key)):
        """Return schemas for all registered node types — used by the UI palette."""
        return {"nodes": available_node_types()}

    @app.get("/api/workflows", response_model=ListResponse)
    async def list_workflows(
        _user: str = Depends(require_api_key),
        page: int = Query(1, ge=1),
        page_size: int = Query(50, ge=1, le=200),
    ):
        all_wfs = store.list_all()
        total = len(all_wfs)
        start = (page - 1) * page_size
        end = start + page_size
        return ListResponse(
            workflows=all_wfs[start:end],
            total=total, page=page, page_size=page_size,
        )

    @app.get("/api/workflows/{wid}")
    async def get_workflow(wid: str, _user: str = Depends(require_api_key)):
        wf = store.load(wid)
        if wf is None:
            raise HTTPException(404, f"Workflow {wid} not found")
        return wf

    @app.post("/api/workflows", status_code=201)
    async def save_workflow(
        wf: WorkflowModel = Body(...),
        _user: str = Depends(require_api_key),
    ):
        saved = store.save(wf.model_dump())
        return saved

    @app.put("/api/workflows/{wid}")
    async def update_workflow(
        wid: str,
        wf: WorkflowModel = Body(...),
        _user: str = Depends(require_api_key),
    ):
        wf.id = wid
        saved = store.save(wf.model_dump())
        return saved

    @app.delete("/api/workflows/{wid}")
    async def delete_workflow(wid: str, _user: str = Depends(require_api_key)):
        store.delete(wid)
        return {"deleted": wid}

    @app.post("/api/run")
    async def run_workflow(
        req: RunRequest, _user: str = Depends(require_api_key)
    ):
        """Execute a workflow definition inline (does not require saving)."""
        wf_def = _wf_dict_for_executor(req.workflow)
        result = await executor.run(wf_def, inputs=req.inputs)
        return result.to_dict()

    @app.post("/api/workflows/{wid}/run")
    async def run_saved_workflow(
        wid: str,
        _user: str = Depends(require_api_key),
        inputs: dict[str, Any] = Body(default_factory=dict),
    ):
        wf_dict = store.load(wid)
        if wf_dict is None:
            raise HTTPException(404, f"Workflow {wid} not found")
        wf_def = _wf_dict_for_executor(wf_dict)
        result = await executor.run(wf_def, inputs=inputs or {})
        return result.to_dict()

    # ─── Static UI (mounted last so it doesn't shadow /api) ──────────
    ui_dir = Path(__file__).resolve().parent.parent / "static"
    if ui_dir.exists():
        app.mount("/", StaticFiles(directory=str(ui_dir), html=True), name="ui")
    else:
        @app.get("/")
        async def root():
            return {
                "message": "Agents-in-the-air API. Build the UI to see the canvas.",
                "docs": "/docs" if settings.env != "production" else None,
                "node_types": "/api/nodes",
            }

    return app


# ─── Storage abstraction ─────────────────────────────────────────────────


class WorkflowStore:
    """JSON-file-backed workflow storage.

    This is a simple interface that can be swapped for a database (Postgres,
    SQLite, etc.) without touching the API layer. Methods are synchronous
    because file I/O is fast for the expected scale; for high-throughput
    deployments, subclass and make the methods async + use aiofiles.
    """

    def __init__(self, data_dir: Path):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    def _path(self, wid: str) -> Path:
        return self.data_dir / f"{wid}.json"

    def save(self, wf_dict: dict[str, Any]) -> dict[str, Any]:
        if not wf_dict.get("id"):
            wf_dict["id"] = uuid.uuid4().hex[:12]
        # write atomically: write to temp then rename
        p = self._path(wf_dict["id"])
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(wf_dict, indent=2, default=str))
        tmp.replace(p)
        return wf_dict

    def load(self, wid: str) -> dict[str, Any] | None:
        p = self._path(wid)
        if not p.exists():
            return None
        try:
            return json.loads(p.read_text())
        except Exception:
            log.warning("Corrupt workflow file: %s", p)
            return None

    def delete(self, wid: str) -> bool:
        p = self._path(wid)
        if p.exists():
            p.unlink()
            return True
        return False

    def list_all(self) -> list[dict[str, Any]]:
        wfs = []
        for p in sorted(self.data_dir.glob("*.json")):
            try:
                wfs.append(json.loads(p.read_text()))
            except Exception:
                continue
        return wfs


# ─── Helpers ─────────────────────────────────────────────────────────────


def _wf_dict_for_executor(wf) -> dict[str, Any]:
    """Strip UI-only fields, keep id/type/config."""
    # Accept either a Pydantic model or a plain dict
    if hasattr(wf, "model_dump"):
        wf = wf.model_dump()
    return {
        "id": wf.get("id"),
        "name": wf.get("name"),
        "nodes": [
            {"id": n["id"], "type": n["type"], "config": n.get("config", {})}
            for n in wf.get("nodes", [])
        ],
    }


# ─── Module-level app for uvicorn ────────────────────────────────────────

app = create_app()
