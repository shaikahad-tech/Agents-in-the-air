"""Tests for the DAG executor: topological sort, parallel execution,
error propagation, cycle detection, timeouts, and template substitution.
"""
import pytest

from app.executor import (
    _topo_sort,
    find_refs,
    resolve_env,
    substitute,
)

# ─── Template parsing ────────────────────────────────────────────────────


class TestTemplateParsing:
    def test_find_refs_simple(self):
        assert find_refs("{{foo}}") == ["foo"]

    def test_find_refs_nested(self):
        assert find_refs("{{foo.bar.baz}}") == ["foo"]

    def test_find_refs_multiple(self):
        refs = find_refs({"a": "{{x}}", "b": ["{{y}}", "{{z.field}}"]})
        assert sorted(refs) == ["x", "y", "z"]

    def test_find_refs_ignores_env(self):
        assert find_refs("${{env:SECRET}}") == []

    def test_substitute_preserves_type(self):
        outputs = {"node1": {"count": 42, "name": "test"}}
        assert substitute("{{node1.count}}", outputs) == 42
        assert substitute("{{node1.name}}", outputs) == "test"

    def test_substitute_embedded(self):
        outputs = {"node1": {"name": "world"}}
        assert substitute("hello {{node1.name}}!", outputs) == "hello world!"

    def test_substitute_dict(self):
        outputs = {"n": {"v": 10}}
        result = substitute({"key": "{{n.v}}", "list": ["{{n.v}}"]}, outputs)
        assert result == {"key": 10, "list": [10]}

    def test_substitute_unknown_ref_raises(self):
        with pytest.raises(KeyError):
            substitute("{{missing}}", {})

    def test_resolve_env(self, monkeypatch):
        monkeypatch.setenv("MY_TEST_SECRET", "secret123")
        assert resolve_env("${{env:MY_TEST_SECRET}}") == "secret123"

    def test_resolve_env_missing_raises(self):
        with pytest.raises(KeyError):
            resolve_env("${{env:NONEXISTENT_VAR_XYZ}}")


# ─── Topological sort ────────────────────────────────────────────────────


class TestTopoSort:
    def test_linear_chain(self):
        nodes_ = [
            {"id": "a", "config": {"v": "{{b}}"}},
            {"id": "b", "config": {"v": "{{c}}"}},
            {"id": "c", "config": {}},
        ]
        order = _topo_sort(nodes_)
        assert order == ["c", "b", "a"]

    def test_parallel_nodes(self):
        nodes_ = [
            {"id": "a", "config": {}},
            {"id": "b", "config": {}},
        ]
        order = _topo_sort(nodes_)
        assert set(order) == {"a", "b"}

    def test_cycle_detection(self):
        nodes_ = [
            {"id": "a", "config": {"v": "{{b}}"}},
            {"id": "b", "config": {"v": "{{a}}"}},
        ]
        with pytest.raises(ValueError, match="Cycle"):
            _topo_sort(nodes_)

    def test_self_reference_detection(self):
        nodes_ = [{"id": "a", "config": {"v": "{{a}}"}}]
        with pytest.raises(ValueError, match="references itself"):
            _topo_sort(nodes_)


# ─── Executor ────────────────────────────────────────────────────────────


class TestExecutor:
    @pytest.mark.asyncio
    async def test_empty_workflow(self, executor):
        result = await executor.run({"id": "empty", "nodes": []})
        assert result.status == "error"
        assert "No nodes" in result.error

    @pytest.mark.asyncio
    async def test_simple_transform(self, executor):
        wf = {
            "id": "test",
            "nodes": [
                {"id": "t", "type": "transform",
                 "config": {"operation": "identity", "data": "hello"}},
            ],
        }
        result = await executor.run(wf)
        assert result.status == "success"
        assert result.nodes["t"].output == "hello"

    @pytest.mark.asyncio
    async def test_error_propagation(self, executor):
        """A failing node should cause downstream nodes to be skipped."""
        wf = {
            "id": "err-test",
            "nodes": [
                {"id": "bad", "type": "transform",
                 "config": {"operation": "NONEXISTENT", "data": "x"}},
                {"id": "downstream", "type": "transform",
                 "config": {"operation": "identity", "data": "{{bad}}"}},
            ],
        }
        result = await executor.run(wf)
        assert result.status == "error"
        assert result.nodes["bad"].status == "error"
        assert result.nodes["downstream"].status == "skipped"

    @pytest.mark.asyncio
    async def test_cycle_returns_error(self, executor):
        wf = {
            "id": "cycle",
            "nodes": [
                {"id": "a", "type": "transform",
                 "config": {"operation": "identity", "data": "{{b}}"}},
                {"id": "b", "type": "transform",
                 "config": {"operation": "identity", "data": "{{a}}"}},
            ],
        }
        result = await executor.run(wf)
        assert result.status == "error"
        assert "Cycle" in result.error

    @pytest.mark.asyncio
    async def test_too_many_nodes(self, executor):
        """Workflow exceeding max_workflow_nodes should be rejected."""
        nodes_ = [{"id": f"n{i}", "type": "transform",
                   "config": {"operation": "identity", "data": i}} for i in range(600)]
        result = await executor.run({"id": "big", "nodes": nodes_})
        assert result.status == "error"
        assert "max" in result.error.lower()

    @pytest.mark.asyncio
    async def test_external_inputs(self, executor):
        wf = {
            "id": "inputs-test",
            "nodes": [
                {"id": "echo", "type": "transform",
                 "config": {"operation": "identity", "data": "{{inputs.msg}}"}},
            ],
        }
        result = await executor.run(wf, inputs={"msg": "from outside"})
        assert result.status == "success"
        assert result.nodes["echo"].output == "from outside"

    @pytest.mark.asyncio
    async def test_result_has_duration(self, executor):
        wf = {
            "id": "dur",
            "nodes": [{"id": "t", "type": "transform",
                       "config": {"operation": "identity", "data": "x"}}],
        }
        result = await executor.run(wf)
        d = result.to_dict()
        assert d["duration_s"] is not None
        assert d["duration_s"] >= 0
