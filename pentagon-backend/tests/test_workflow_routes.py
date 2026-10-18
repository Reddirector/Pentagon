import pytest
from fastapi.testclient import TestClient

from app.main import app


@pytest.fixture
def test_client():
    return TestClient(app)


def test_list_workflows_returns_templates_and_user_workflows(test_client):
    user_id = "test-user-wf-1"
    res = test_client.get(f"/api/workflows?user_id={user_id}")
    assert res.status_code == 200
    data = res.json()
    assert "templates" in data
    assert "workflows" in data
    assert len(data["templates"]) >= 3
    template_ids = [t["id"] for t in data["templates"]]
    assert "tpl-deep-market-research" in template_ids
    assert "tpl-pitch-deck-financials" in template_ids
    assert "tpl-content-visual-suite" in template_ids


def test_create_and_delete_custom_workflow(test_client):
    user_id = "test-user-wf-create"
    payload = {
        "user_id": user_id,
        "name": "Custom Content Pipeline",
        "description": "Generates market update",
        "icon": "zap",
        "category": "marketing",
        "nodes": [
            {
                "id": "step_trigger",
                "type": "trigger",
                "title": "Inputs",
                "config": {"topic": "AI"},
            },
            {
                "id": "step_search",
                "type": "web_search",
                "title": "Search",
                "config": {"query": "{{inputs.topic}}"},
            },
        ],
        "edges": [{"source": "step_trigger", "target": "step_search"}],
    }
    # Create workflow
    res = test_client.post("/api/workflows", json=payload)
    assert res.status_code == 200
    created = res.json()
    assert created["name"] == "Custom Content Pipeline"
    wf_id = created["id"]

    # Read back workflow
    get_res = test_client.get(f"/api/workflows/{wf_id}?user_id={user_id}")
    assert get_res.status_code == 200
    assert get_res.json()["name"] == "Custom Content Pipeline"

    # Delete workflow
    del_res = test_client.delete(f"/api/workflows/{wf_id}?user_id={user_id}")
    assert del_res.status_code == 200

    # 404 after deletion
    del_check = test_client.get(f"/api/workflows/{wf_id}?user_id={user_id}")
    assert del_check.status_code == 404


def test_create_workflow_detects_cycles(test_client):
    user_id = "test-user-wf-cycle"
    payload = {
        "user_id": user_id,
        "name": "Cyclic Flow",
        "description": "Invalid cycle",
        "nodes": [
            {"id": "n1", "type": "step", "title": "Node 1"},
            {"id": "n2", "type": "step", "title": "Node 2"},
        ],
        "edges": [
            {"source": "n1", "target": "n2"},
            {"source": "n2", "target": "n1"},
        ],
    }
    res = test_client.post("/api/workflows", json=payload)
    assert res.status_code == 400
    assert "cycle" in res.json()["detail"].lower()
