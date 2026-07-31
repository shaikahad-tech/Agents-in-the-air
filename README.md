# ⚡ Agents-in-the-air

A drag-and-drop agentic workflow builder. Compose automations visually on a canvas — LLM calls, HTTP requests, Python code, file ops, and data transforms — then run the whole DAG with one click.

- **Visual canvas** (React Flow) — drag nodes, wire them together, configure each node in a side panel.
- **Python DAG runtime** (FastAPI + asyncio) — topologically executes your graph, parallelising independent nodes.
- **Cloud-deployable** — ships with a `Dockerfile` and `render.yaml`.

> You bring the API keys. Wire them into the deployment environment (`.env` / Render dashboard), then reference them in any node config as `${{env:MY_KEY}}`. Keys never live inside the workflow JSON.

---

## Architecture

```
Frontend (React + React Flow)     Backend (FastAPI + asyncio)
  drag/drop canvas                   /api/nodes      node schemas
  palette of node types               /api/workflows  CRUD
  per-node config panel     <--JSON--> /api/run        execute DAG
  run + result viewer                 WorkflowExecutor
                                      llm http code file transform
```

### Execution model

A workflow is a DAG. Each node produces an output. Downstream nodes reference upstream outputs with `{{node_id.field}}` templates, and secrets with `${{env:NAME}}`. The executor:

1. Scans configs for `{{refs}}` to build a dependency graph.
2. Topologically sorts nodes into parallel waves.
3. Runs each wave concurrently with `asyncio.gather`.
4. Substitutes template values before each node runs.

---

## Built-in node types

| Type | What it does |
|------|--------------|
| `llm` | Call OpenAI / Anthropic / Gemini. Supports system+user prompts, temperature, JSON mode. |
| `http` | REST request (GET/POST/PUT/PATCH/DELETE) with headers, query, JSON body. |
| `code` | Run a Python snippet. Access upstream outputs via `inputs`; set `result` or define `main()`. |
| `file` | Read / write / list / delete files in the workspace. Auto-parses JSON & CSV. |
| `transform` | Reshape data without code: extract, map, filter, flatten, to_csv, json_path, template. |

### Referencing between nodes

In any config field, use these template syntaxes:

```
{{fetch_weather.body.main.temp}}     # output of node "fetch_weather", drilled into body.main.temp
{{summarize.text}}                    # the "text" key of node "summarize"'s output
${{env:OPENAI_API_KEY}}               # resolved from the environment at run time
```

---

## Quick start (local)

### 1. Backend

```bash
cd backend
pip install -e .
cp ../.env.example ../.env   # then edit .env with your API keys
python run.py                 # serves http://localhost:8000
```

### 2. Frontend (dev mode)

```bash
cd frontend
npm install
npm run dev                  # serves http://localhost:5173, proxies /api to :8000
```

Open http://localhost:5173 to use the canvas.

### Pre-built UI

The repo includes a pre-built `backend/static/index.html`. To produce the full UI bundle, run `cd frontend && npm run build` (outputs to `backend/static/`). The Dockerfile handles this automatically during the build stage.

---

## Deploy

### Render (one-click via Blueprint)

1. Push this repo to GitHub.
2. In Render: **New -> Blueprint**, select the repo. Render reads `render.yaml`.
3. In the Render dashboard, fill in the secret env vars (`OPENAI_API_KEY`, etc.) — they're marked `sync: false` so they're not committed.

### Docker

```bash
docker build -t agents-in-the-air .
docker run -p 8000:8000 --env-file .env -v $(pwd)/data:/data agents-in-the-air
```

### Fly / Railway

The Dockerfile works on any container platform. Set the same env vars (`OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, `AITA_DATA`, `AITA_WORKSPACE`) in the platform's dashboard, and mount a volume at `/data` if you want workflows to persist.

---

## Example workflow

A research-summarise-send pipeline (see `examples/research_summary.json`):

```
[fetch_news: http] -> [summarise: llm] -> [save: file]
        \-> [extract: transform]
```

Run it via the API:

```bash
curl -X POST http://localhost:8000/api/run \
  -H "Content-Type: application/json" \
  -d @examples/research_summary.json
```

Or load `examples/research_summary.json` into the canvas and click **Run**.

---

## Adding a custom node

1. Create `backend/app/nodes/my_node.py`:

```python
from ..registry import BaseNode, register_node

@register_node("my_node")
class MyNode(BaseNode):
    """Does a thing. Returns {"result": ...}."""

    async def run(self):
        val = self.config.get("value")
        return {"result": f"processed {val}"}

    @classmethod
    def schema(cls):
        return {
            "type": "my_node", "label": "My Node", "color": "#14b8a6",
            "fields": [{"name": "value", "type": "string", "default": ""}],
        }
```

2. Register it in `backend/app/nodes/__init__.py`.
3. It appears in the UI palette automatically and is runnable via `/api/run`.

---

## API reference

| Method | Path | Description |
|--------|------|-------------|
| GET | `/api/health` | Liveness + registered node types |
| GET | `/api/nodes` | Schemas for all node types (UI palette) |
| GET | `/api/workflows` | List saved workflows |
| GET | `/api/workflows/{id}` | Get one workflow |
| POST | `/api/workflows` | Create/save a workflow |
| PUT | `/api/workflows/{id}` | Update a workflow |
| DELETE | `/api/workflows/{id}` | Delete a workflow |
| POST | `/api/run` | Execute a workflow definition inline |
| POST | `/api/workflows/{id}/run` | Execute a saved workflow |

Interactive docs at `/docs` (Swagger UI).

---

## Security notes

- The `code` node runs Python with a restricted builtins set but is **not** a security sandbox. For untrusted workflows, run the executor inside a container with tightened seccomp/apparmor.
- Secrets are read from the environment at execution time and never persisted in the workflow JSON.
- File nodes are scoped to a workspace root (`AITA_WORKSPACE`); path traversal is rejected.

---

## License

MIT
