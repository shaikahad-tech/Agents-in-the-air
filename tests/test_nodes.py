"""Tests for individual node implementations: transform, code, file, http, llm stub.
"""
import pytest

from app import nodes  # noqa
from app.executor import WorkflowExecutor
from app.registry import BaseNode, register_node

# ─── Transform node ──────────────────────────────────────────────────────


class TestTransformNode:
    @pytest.mark.asyncio
    async def test_identity(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "transform",
             "config": {"operation": "identity", "data": {"a": 1}}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].output == {"a": 1}

    @pytest.mark.asyncio
    async def test_extract(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "transform",
             "config": {"operation": "extract", "data": {"a": {"b": 5}}, "field": "a.b"}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].output == 5

    @pytest.mark.asyncio
    async def test_map(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "transform",
             "config": {"operation": "map", "data": [{"x": 1}, {"x": 2}], "field": "x"}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].output == [1, 2]

    @pytest.mark.asyncio
    async def test_filter(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "transform",
             "config": {"operation": "filter", "data": [
                 {"price": 50}, {"price": 150}, {"price": 200}
             ], "expr": "price>=150"}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].output == [{"price": 150}, {"price": 200}]

    @pytest.mark.asyncio
    async def test_flatten(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "transform",
             "config": {"operation": "flatten", "data": [[1, 2], [3], [4, 5]]}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].output == [1, 2,3,4,5]

    @pytest.mark.asyncio
    async def test_to_csv(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "transform",
             "config": {"operation": "to_csv", "data": [{"a": 1, "b": 2}]}}
        ]}
        r = await executor.run(wf)
        assert "a,b" in r.nodes["n"].output
        assert "1,2" in r.nodes["n"].output

    @pytest.mark.asyncio
    async def test_template(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "transform",
             "config": {"operation": "template",
                        "data": {"name": "World"},
                        "expr": "Hello, {name}!"}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].output == "Hello, World!"


# ─── Code node ──────────────────────────────────────────────────────────


class TestCodeNode:
    @pytest.mark.asyncio
    async def test_basic(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "code", "config": {"code": "result = 42"}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].output == 42

    @pytest.mark.asyncio
    async def test_with_inputs(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "code",
             "config": {"code": "result = inputs['x'] * 3", "x": 14}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].output == 42

    @pytest.mark.asyncio
    async def test_main(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "code",
             "config": {"code": "def main():\n    return {'ok': True}"}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].output == {"ok": True}

    @pytest.mark.asyncio
    async def test_blocked_import(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "n", "type": "code",
             "config": {"code": "import os\nresult = os.getuid()"}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["n"].status == "error"


# ─── File node ───────────────────────────────────────────────────────────


class TestFileNode:
    @pytest.mark.asyncio
    async def test_write_and_read(self, executor):
        wf_write = {"id": "t", "nodes": [
            {"id": "w", "type": "file",
             "config": {"operation": "write", "path": "test_file.txt",
                        "content": "hello world"}}
        ]}
        r = await executor.run(wf_write)
        assert r.nodes["w"].output["status"] == "written"

        wf_read = {"id": "t", "nodes": [
            {"id": "r", "type": "file",
             "config": {"operation": "read", "path": "test_file.txt"}}
        ]}
        r2 = await executor.run(wf_read)
        assert r2.nodes["r"].output["content"] == "hello world"

    @pytest.mark.asyncio
    async def test_path_traversal_blocked(self, executor):
        wf = {"id": "t", "nodes": [
            {"id": "r", "type": "file",
             "config": {"operation": "read", "path": "../../../etc/passwd"}}
        ]}
        r = await executor.run(wf)
        assert r.nodes["r"].status == "error"
        assert "workspace" in r.nodes["r"].error.lower()

    @pytest.mark.asyncio
    async def test_list(self, executor):
        # write a file first
        await executor.run({"id": "t", "nodes": [
            {"id": "w", "type": "file",
             "config": {"operation": "write", "path": "list_test.txt", "content": "x"}}
        ]})
        wf = {"id": "t", "nodes": [
            {"id": "l", "type": "file", "config": {"operation": "list", "path": "."}}
        ]}
        r = await executor.run(wf)
        names = [e["name"] for e in r.nodes["l"].output["entries"]]
        assert "list_test.txt" in names

    @pytest.mark.asyncio
    async def test_json_read(self, executor):
        await executor.run({"id": "t", "nodes": [
            {"id": "w", "type": "file",
             "config": {"operation": "write", "path": "data.json",
                        "content": {"key": "value", "num": 42}}}
        ]})
        r = await executor.run({"id": "t", "nodes": [
            {"id": "r", "type": "file",
             "config": {"operation": "read", "path": "data.json"}}
        ]})
        assert r.nodes["r"].output["content"]["key"] == "value"


# ─── LLM node (with stub) ────────────────────────────────────────────────


class TestLLMNode:
    @pytest.mark.asyncio
    async def test_stub_llm(self, settings):
        """Test LLM node with a stub provider (no real API call)."""
        from app.registry import NODE_TYPES

        # Save original, register stub, restore after
        original_llm = NODE_TYPES.get("llm")

        @register_node("llm")
        class StubLLM(BaseNode):
            async def run(self):
                return {"text": f"[STUB] {self.config.get('user', '')[:20]}",
                        "usage": {}, "model": "stub"}

        try:
            executor = WorkflowExecutor(settings=settings)
            wf = {"id": "t", "nodes": [
                {"id": "l", "type": "llm",
                 "config": {"provider": "openai", "model": "gpt-4o-mini",
                            "api_key": "fake", "user": "Summarise this: hello world"}}
            ]}
            r = await executor.run(wf)
            assert r.nodes["l"].output["text"].startswith("[STUB]")
            assert r.nodes["l"].output["model"] == "stub"
        finally:
            if original_llm is not None:
                NODE_TYPES["llm"] = original_llm
