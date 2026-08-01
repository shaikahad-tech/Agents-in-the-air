"""Tests for the API layer: CRUD, health, run endpoint, pagination, auth.
"""


class TestHealth:
    def test_health(self, client):
        r = client.get("/api/health")
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "ok"
        assert "node_types" in data
        assert "llm" in data["node_types"]
        assert "http" in data["node_types"]
        assert data["version"]


class TestNodeSchemas:
    def test_list_nodes(self, client):
        r = client.get("/api/nodes")
        assert r.status_code == 200
        nodes = r.json()["nodes"]
        types = [n["type"] for n in nodes]
        assert "llm" in types
        assert "http" in types
        assert "code" in types
        assert "file" in types
        assert "transform" in types

    def test_node_schema_has_fields(self, client):
        r = client.get("/api/nodes")
        nodes = r.json()["nodes"]
        llm = [n for n in nodes if n["type"] == "llm"][0]
        assert "fields" in llm["schema"]
        field_names = [f["name"] for f in llm["schema"]["fields"]]
        assert "provider" in field_names
        assert "model" in field_names
        assert "api_key" in field_names


class TestWorkflowCRUD:
    def test_create_and_get(self, client):
        wf = {"name": "Test WF", "nodes": [], "edges": []}
        r = client.post("/api/workflows", json=wf)
        assert r.status_code == 201
        created = r.json()
        assert created["id"]
        assert created["name"] == "Test WF"

        # GET it back
        r2 = client.get(f"/api/workflows/{created['id']}")
        assert r2.status_code == 200
        assert r2.json()["name"] == "Test WF"

    def test_update(self, client):
        wf = {"name": "Original", "nodes": [], "edges": []}
        r = client.post("/api/workflows", json=wf)
        wid = r.json()["id"]

        r2 = client.put(f"/api/workflows/{wid}", json={"name": "Updated", "nodes": [], "edges": []})
        assert r2.status_code == 200
        assert r2.json()["name"] == "Updated"

    def test_delete(self, client):
        wf = {"name": "ToDelete", "nodes": [], "edges": []}
        r = client.post("/api/workflows", json=wf)
        wid = r.json()["id"]

        r2 = client.delete(f"/api/workflows/{wid}")
        assert r2.status_code == 200

        r3 = client.get(f"/api/workflows/{wid}")
        assert r3.status_code == 404

    def test_get_nonexistent(self, client):
        r = client.get("/api/workflows/nonexistent123")
        assert r.status_code == 404

    def test_validation_empty_name(self, client):
        r = client.post("/api/workflows", json={"name": "", "nodes": [], "edges": []})
        assert r.status_code == 422

    def test_list_pagination(self, client):
        # Create several workflows
        for i in range(5):
            client.post("/api/workflows", json={"name": f"WF{i}", "nodes": [], "edges": []})

        r = client.get("/api/workflows?page=1&page_size=3")
        assert r.status_code == 200
        data = r.json()
        assert data["total"] >= 5
        assert data["page"] == 1
        assert data["page_size"] == 3
        assert len(data["workflows"]) <= 3

        r2 = client.get("/api/workflows?page=2&page_size=3")
        assert r2.status_code == 200


class TestRunEndpoint:
    def test_run_inline(self, client):
        wf = {
            "name": "Inline Run",
            "nodes": [
                {"id": "t", "type": "transform",
                 "config": {"operation": "identity", "data": "hello"}},
            ],
            "edges": [],
        }
        r = client.post("/api/run", json={"workflow": wf, "inputs": {}})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "success"
        assert data["nodes"]["t"]["output"] == "hello"

    def test_run_with_inputs(self, client):
        wf = {
            "name": "Inputs Test",
            "nodes": [
                {"id": "echo", "type": "transform",
                 "config": {"operation": "identity", "data": "{{inputs.msg}}"}},
            ],
            "edges": [],
        }
        r = client.post("/api/run", json={"workflow": wf, "inputs": {"msg": "hi"}})
        assert r.status_code == 200
        assert r.json()["nodes"]["echo"]["output"] == "hi"

    def test_run_error(self, client):
        wf = {
            "name": "Error Test",
            "nodes": [
                {"id": "bad", "type": "transform",
                 "config": {"operation": "BAD_OP", "data": "x"}},
            ],
            "edges": [],
        }
        r = client.post("/api/run", json={"workflow": wf, "inputs": {}})
        assert r.status_code == 200
        assert r.json()["status"] == "error"

    def test_run_saved_workflow(self, client):
        wf = {
            "name": "Saved Run",
            "nodes": [
                {"id": "t", "type": "transform",
                 "config": {"operation": "identity", "data": "saved-hello"}},
            ],
            "edges": [],
        }
        r = client.post("/api/workflows", json=wf)
        wid = r.json()["id"]

        r2 = client.post(f"/api/workflows/{wid}/run")
        assert r2.status_code == 200
        assert r2.json()["status"] == "success"

    def test_run_saved_nonexistent(self, client):
        r = client.post("/api/workflows/nonexistent/run")
        assert r.status_code == 404


class TestNodeTypes:
    def test_http_node_rejects_private_ip(self, client):
        """HTTP node should reject requests to private IPs (SSRF)."""
        wf = {
            "name": "SSRF Test",
            "nodes": [
                {"id": "bad", "type": "http",
                 "config": {"method": "GET", "url": "http://192.168.1.1/admin"}},
            ],
            "edges": [],
        }
        r = client.post("/api/run", json={"workflow": wf, "inputs": {}})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert "SSRF" in data["nodes"]["bad"]["error"]

    def test_code_node_blocks_import(self, client):
        """Code node should block importing os."""
        wf = {
            "name": "Sandbox Test",
            "nodes": [
                {"id": "c", "type": "code",
                 "config": {"code": "import os\nresult = os.listdir('/')"}},
            ],
            "edges": [],
        }
        r = client.post("/api/run", json={"workflow": wf, "inputs": {}})
        assert r.status_code == 200
        data = r.json()
        assert data["status"] == "error"
        assert "blocked" in data["nodes"]["c"]["error"].lower() or \\
               "import" in data["nodes"]["c"]["error"].lower()
