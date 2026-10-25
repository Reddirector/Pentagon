"""Tests for the Localhost Server Manager and API Endpoints."""

import httpx
import pytest
from app.services.localhost_server import LOCALHOST_MANAGER, find_free_port


def test_find_free_port():
    port = find_free_port(start=8900)
    assert 8900 <= port < 9200


def test_localhost_server_serves_html():
    sample_html = "<!DOCTYPE html><html><body><h1>Hello Localhost</h1></body></html>"
    result = LOCALHOST_MANAGER.start_server(
        html=sample_html,
        title="Test Localhost App",
        port=None,
    )
    assert result["ok"] is True
    port = result["port"]
    url = result["url"]
    assert url == f"http://localhost:{port}"

    try:
        # Request the localhost server
        resp = httpx.get(f"http://127.0.0.1:{port}", timeout=5.0)
        assert resp.status_code == 200
        assert "Hello Localhost" in resp.text
        assert resp.headers["content-type"].startswith("text/html")
        assert resp.headers.get("x-served-by") == "Pentagon-Localhost-Server"

        # Check healthz
        health = httpx.get(f"http://127.0.0.1:{port}/healthz", timeout=5.0)
        assert health.status_code == 200
        assert health.json()["status"] == "ok"
    finally:
        LOCALHOST_MANAGER.stop_server(port)


def test_localhost_server_lifecycle():
    sample_html = "<html><body>Lifecycle Test</body></html>"
    res = LOCALHOST_MANAGER.start_server(html=sample_html, title="Lifecycle")
    port = res["port"]
    srv_id = res["server_id"]

    active = LOCALHOST_MANAGER.list_servers()
    ports = [s["port"] for s in active]
    assert port in ports

    stopped = LOCALHOST_MANAGER.stop_server(srv_id)
    assert stopped is True

    active_after = LOCALHOST_MANAGER.list_servers()
    ports_after = [s["port"] for s in active_after]
    assert port not in ports_after


def test_serve_website_locally_tool():
    import asyncio
    from app.agent.schemas import ToolContext
    from app.tools import serve_website_locally

    ctx = ToolContext(user_id="usr_123", conversation_id="conv_123", turn_id="t0", permission_level=2)
    res = asyncio.run(
        serve_website_locally.run(
            {"html": "<h1>Autonomous Agent Website</h1>", "title": "Agent Site"},
            ctx,
        )
    )
    assert res.ok is True
    assert "url" in res.data
    assert "http://localhost:" in res.data["url"]
    port = res.data["port"]
    LOCALHOST_MANAGER.stop_server(port)


def test_localhost_api_endpoints():
    from starlette.testclient import TestClient
    from app.main import app

    with TestClient(app) as client:
        # 1. Start server via API
        resp = client.post(
            "/api/localhost/start",
            json={
                "html": "<html><body><h1>Localhost API Test</h1></body></html>",
                "title": "API Test",
            },
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["ok"] is True
        assert "http://localhost:" in data["url"]
        port = data["port"]

        try:
            # 2. Check active servers list
            list_resp = client.get("/api/localhost/servers")
            assert list_resp.status_code == 200
            servers = list_resp.json()
            active_ports = [s["port"] for s in servers]
            assert port in active_ports

            # 3. Test HTTP reachability
            direct = httpx.get(f"http://127.0.0.1:{port}", timeout=5.0)
            assert direct.status_code == 200
            assert "Localhost API Test" in direct.text

            # 4. Stop server via API
            stop_resp = client.post("/api/localhost/stop", json={"port": port})
            assert stop_resp.status_code == 200
            assert stop_resp.json()["ok"] is True
        finally:
            LOCALHOST_MANAGER.stop_server(port)
