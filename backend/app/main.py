"""FastAPI app: workflow CRUD, node schemas, run endpoint, static UI."""
from __future__ import annotations

import json
import os
import uuid
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from .executor import WorkflowExecutor
from .registry import available_node_types
from . import nodes  # noqa: F401  — registers node types

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("aita.api")

WORKFLOWS_DIR = Path(os.environ.get("AITA_DATA", "/tmp/aita/data"))
WORKFLOWS_DIR.mkdir(parents=True, exist_ok=True)

app = FastAPI(title="Agents-in-the-air", version="0.1.0",
              description="Drag-and-drop agentic workflow builder.")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

executor = WorkflowExecutor()


# --- models ----------------------------------------------------------------


class NodeModel(BaseModel):
    id: str
    type: str
    config: Dict[str, Any] = Field(default_factory=dict)
    # UI-only fields (position, etc.) — ignored by executor
    position: Optional[Dict[str, float]] = None
    data: Optional[Dict[str, Any]] = None


class EdgeModel(BaseModel):
    id: Optional[str] = None
    source: str
    target: str
    sourceHandle: Optional[str] = None
    targetHandle: Optional[str] = None


class WorkflowModel(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    nodes: List[NodeModel] = []
    edges: List[EdgeModel] = []


class RunRequest(BaseModel):
    workflow: WorkflowModel
    inputs: Dict[str, Any] = Field(default_factory=dict)


# --- helpers ---------------------------------------------------------------


def _wf_path(wid: str) -> Path:
    return WORKFLOWS_DIR / f"{wid}.json"


def _save(wf: WorkflowModel) -> WorkflowModel:
    if not wf.id:
        wf.id = uuid.uuid4().hex[:12]
    p = _wf_path(wf.id)
    p.write_text(wf.model_dump_json(indent=2))
    return wf


def _load(wid: str) -> WorkflowModel:
    p = _wf_path(wid)
    if not p.exists():
        raise HTTPException(404, f"Workflow {wid} not found")
    return WorkflowModel(**json.loads(p.read_text()))


def _wf_dict_for_executor(wf: WorkflowModel) -> Dict[str, Any]:
    """Strip UI-only fields, keep id/type/config."""
    return {
        "id": wf.id,
        "name": wf.name,
        "nodes": [{"id": n.id, "type": n.type, "config": n.config} for n in wf.nodes],
    }


# --- routes ----------------------------------------------------------------


@app.get("/api/health")
async def health():
    return {"status": "ok", "node_types": [t["type"] for t in available_node_types()]}


@app.get("/api/nodes")
async def list_node_types():
    """Return schemas for all registered node types — used by the UI palette."""
    return {"nodes": available_node_types()}


@app.get("/api/workflows")
async def list_workflows():
    wfs = []
    for p in sorted(WORKFLOWS_DIR.glob("*.json")):
        try:
            wfs.append(json.loads(p.read_text()))
        except Exception:
            continue
    return {"workflows": wfs}


@app.get("/api/workflows/{wid}")
async def get_workflow(wid: str):
    return _load(wid).model_dump()


@app.post("/api/workflows", status_code=201)
async def save_workflow(wf: WorkflowModel):
    saved = _save(wf)
    return saved.model_dump()


@app.put("/api/workflows/{wid}")
async def update_workflow(wid: str, wf: WorkflowModel):
    wf.id = wid
    saved = _save(wf)
    return saved.model_dump()


@app.delete("/api/workflows/{wid}")
async def delete_workflow(wid: str):
    p = _wf_path(wid)
    if p.exists():
        p.unlink()
    return {"deleted": wid}


@app.post("/api/run")
async def run_workflow(req: RunRequest):
    """Execute a workflow definition inline (does not require saving)."""
    wf_def = _wf_dict_for_executor(req.workflow)
    result = await executor.run(wf_def, inputs=req.inputs)
    return result.to_dict()


@app.post("/api/workflows/{wid}/run")
async def run_saved_workflow(wid: str, inputs: Dict[str, Any] = None):
    wf = _load(wid)
    wf_def = _wf_dict_for_executor(wf)
    result = await executor.run(wf_def, inputs=inputs or {})
    return result.to_dict()


# --- static UI (mounted last so it doesn't shadow /api) --------------------

UI_DIR = Path(__file__).resolve().parent.parent / "static"
if UI_DIR.exists():
    app.mount("/", StaticFiles(directory=str(UI_DIR), html=True), name="ui")
else:
    @app.get("/")
    async def root():
        return {"message": "Agents-in-the-air API. Build the UI to see the canvas.",
                "docs": "/docs", "node_types": "/api/nodes"}
