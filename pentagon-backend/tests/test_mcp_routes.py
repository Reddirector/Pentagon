import sys
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_MINIMAL_MCP_SERVER_CODE = (
    "import sys, json\n"
    "for line in sys.stdin:\n"
    "    if not line.strip(): continue\n"
    "    msg = json.loads(line)\n"
    "    if 'id' not in msg: continue\n"
    "    m = msg.get('method')\n"
    "    if m == 'initialize':\n"
    "        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'protocolVersion': '2024-11-05', 'capabilities': {}, 'serverInfo': {'name': 'test', 'version': '1'}}}) + '\\n')\n"
    "        sys.stdout.flush()\n"
    "    elif m == 'tools/list':\n"
    "        sys.stdout.write(json.dumps({'jsonrpc': '2.0', 'id': msg['id'], 'result': {'tools': [{'name': 'echo', 'description': 'echo tool', 'inputSchema': {'type': 'object'}}]}}) + '\\n')\n"
    "        sys.stdout.flush()\n"
)


def test_list_mcp_servers():
    response = client.get("/api/mcp")
    assert response.status_code == 200
    data = response.json()
    assert "servers" in data
    assert "presets" in data
    assert any(p["id"] == "sqlite" for p in data["presets"])


def test_create_and_delete_mcp_server():
    # 1. Create a server that runs a tiny inline python script
    payload = {
        "name": "unit_test_server",
        "command": [sys.executable, "-c", _MINIMAL_MCP_SERVER_CODE],
        "tier": "read",
        "env": {"FOO": "bar"},
        "enabled": True,
    }
    create_resp = client.post("/api/mcp", json=payload)
    assert create_resp.status_code == 200
    data = create_resp.json()
    assert data["ok"] is True
    assert data["server"]["name"] == "unit_test_server"
    assert data["server"]["status"] == "connected"
    assert data["server"]["tools_count"] == 1
    assert data["server"]["tools"][0]["name"] == "mcp_unit_test_server_echo"

    # 2. Toggle off
    toggle_resp = client.patch("/api/mcp/unit_test_server/toggle", json={"enabled": False})
    assert toggle_resp.status_code == 200
    assert toggle_resp.json()["enabled"] is False
    assert toggle_resp.json()["status"] == "disabled"

    # 3. Toggle on
    toggle_resp2 = client.patch("/api/mcp/unit_test_server/toggle", json={"enabled": True})
    assert toggle_resp2.status_code == 200
    assert toggle_resp2.json()["enabled"] is True

    # 4. Delete
    del_resp = client.delete("/api/mcp/unit_test_server")
    assert del_resp.status_code == 200
    assert del_resp.json()["ok"] is True


def test_adhoc_mcp_test():
    payload = {
        "command": [sys.executable, "-c", _MINIMAL_MCP_SERVER_CODE],
        "tier": "read",
        "env": {},
    }
    resp = client.post("/api/mcp/test", json=payload)
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["tools_count"] == 1
    assert data["tools"][0]["remote_name"] == "echo"
