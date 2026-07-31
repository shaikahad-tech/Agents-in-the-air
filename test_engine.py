"""End-to-end test of the engine without needing real LLM API keys.

We override the `llm` node type with a stub so the example workflow runs
fully in the sandbox. The HTTP, file, transform, and code nodes run for real.
"""
import asyncio
import json
import sys
import os
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
os.environ["AITA_WORKSPACE"] = "/tmp/aita-test-ws"
os.makedirs("/tmp/aita-test-ws", exist_ok=True)
os.environ["OPENAI_API_KEY"] = "test-key-not-real"

from app.executor import WorkflowExecutor
from app.registry import BaseNode, register_node
from app import nodes  # noqa: register real nodes


@register_node("llm")
class StubLLM(BaseNode):
    """Stub LLM that echoes config — lets us test the DAG without API keys."""
    async def run(self):
        user = self.config.get("user", "")
        return {"text": f"[STUB LLM] processed: {user[:80]}", "model": "stub", "usage": {}}


_LOCAL_JSON = {"slideshow": {"title": "Sample Slideshow", "slides": [{"title": "a"}, {"title": "b"}]}}


class _H(BaseHTTPRequestHandler):
    def do_GET(self):
        body = json.dumps(_LOCAL_JSON).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
    def log_message(self, *a): pass


_srv = HTTPServer(("127.0.0.1", 0), _H)
_PORT = _srv.server_address[1]
threading.Thread(target=_srv.serve_forever, daemon=True).start()


workflow1 = {
    "id": "test-pipeline",
    "nodes": [
        {"id": "http_bin", "type": "http",
         "config": {"method": "GET", "url": f"http://127.0.0.1:{_PORT}/json"}},
        {"id": "extract_slideshow", "type": "transform",
         "config": {"operation": "json_path", "data": "{{http_bin.body}}", "field": "slideshow.title"}},
        {"id": "save", "type": "file",
         "config": {"operation": "write", "path": "slideshow_title.txt", "content": "Title found: {{extract_slideshow}}"}},
        {"id": "code_node", "type": "code",
         "config": {"code": "result = {'upper': inputs['title'].upper(), 'len': len(inputs['title'])}", "title": "{{extract_slideshow}}"}},
        {"id": "llm_node", "type": "llm",
         "config": {"provider": "openai", "model": "gpt-4o-mini", "api_key": "${{env:OPENAI_API_KEY}}",
                    "system": "You are a test assistant.", "user": "Summarise this: {{extract_slideshow}}"}},
    ],
}

workflow2 = {
    "id": "error-test",
    "nodes": [
        {"id": "bad_http", "type": "http",
         "config": {"method": "GET", "url": "https://httpbin.org/status/500"}},
        {"id": "downstream", "type": "transform",
         "config": {"operation": "identity", "data": "{{bad_http.body}}"}},
    ],
}

workflow3 = {
    "id": "cycle-test",
    "nodes": [
        {"id": "a", "type": "transform", "config": {"operation": "identity", "data": "{{b}}"}},
        {"id": "b", "type": "transform", "config": {"operation": "identity", "data": "{{a}}"}},
    ],
}


async def run_all():
    ex = WorkflowExecutor()

    print("\n=== Test 1: full pipeline (http → transform → file → code → llm) ===")
    r1 = await ex.run(workflow1)
    print(json.dumps(r1.to_dict(), indent=2, default=str)[:3000])
    assert r1.status == "success", f"Expected success, got {r1.status}"
    assert r1.nodes["save"].output["status"] == "written"
    assert r1.nodes["code_node"].output["upper"].isupper()

    print("\n=== Test 2: error propagation (HTTP 500 → downstream skipped) ===")
    r2 = await ex.run(workflow2)
    print(json.dumps(r2.to_dict(), indent=2, default=str))
    assert r2.status == "error"
    assert r2.nodes["downstream"].status == "error"

    print("\n=== Test 3: cycle detection ===")
    r3 = await ex.run(workflow3)
    print(json.dumps(r3.to_dict(), indent=2, default=str))
    assert r3.status == "error"

    print("\n✅ All engine tests passed.")


if __name__ == "__main__":
    asyncio.run(run_all())
