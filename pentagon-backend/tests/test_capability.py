"""The capability token: that knowing a ``user_id`` is no longer enough.

The property under test is negative -- a caller with a valid user id and no
token must be refused -- plus the boring mechanics around it: the file is
created privately, is stable across calls, and is compared in constant time.
"""

from __future__ import annotations

import os
import stat

import pytest
from fastapi.testclient import TestClient

from app.db.session import initialize_database
from app.main import app
from app.services import capability

HEADER = "X-Pentagon-Capability"


@pytest.fixture(autouse=True)
def isolated_token(tmp_path, monkeypatch):
    """Every test gets its own token file, and a cold in-process cache."""
    from app.config import settings

    path = tmp_path / "nested" / "capability-token"
    monkeypatch.setattr(settings, "capability_token_path", str(path))
    capability.reset_cache()
    yield path
    capability.reset_cache()


@pytest.fixture
def token() -> str:
    return capability.load_or_create()


@pytest.fixture
def bare() -> TestClient:
    initialize_database()
    return TestClient(app, headers={HEADER: ""})


def _paths() -> tuple[str, str, str]:
    return "/api/commands/settings", "/api/commands/pending", "/api/commands/decide"


def test_token_is_created_privately(isolated_token):
    capability.load_or_create()
    assert isolated_token.is_file()
    mode = stat.S_IMODE(os.stat(isolated_token).st_mode)
    assert mode == 0o600, f"expected 0600, got {oct(mode)}"


def test_token_is_stable_within_and_across_reads(isolated_token):
    first = capability.load_or_create()
    capability.reset_cache()
    assert capability.load_or_create() == first
    assert isolated_token.read_text().strip() == first


def test_token_is_long_and_random(isolated_token):
    value = capability.load_or_create()
    assert len(value) >= 32
    capability.reset_cache()
    assert capability.load_or_create(force_new=True) != value


def test_verify_accepts_only_the_exact_token(token):
    assert capability.verify(token) is True
    assert capability.verify(token + "x") is False
    assert capability.verify(token[:-1]) is False
    assert capability.verify("") is False
    assert capability.verify(None) is False


def test_every_commands_route_refuses_a_bare_user_id(bare):
    """The whole point: the user id alone authorises nothing."""
    settings_path, pending_path, decide_path = _paths()
    assert bare.get(settings_path, params={"user_id": "u1"}).status_code == 401
    assert bare.put(
        settings_path, params={"user_id": "u1"}, json={"enabled": True}
    ).status_code == 401
    assert bare.get(
        pending_path, params={"user_id": "u1", "conversation_id": "c"}
    ).status_code == 401
    assert bare.post(
        decide_path,
        json={"request_id": "r", "approved": True, "user_id": "u1"},
    ).status_code == 401


def test_a_guessed_token_is_refused(bare):
    assert bare.get(
        "/api/commands/settings",
        params={"user_id": "u1"},
        headers={HEADER: "guessed-but-wrong"},
    ).status_code == 401


def test_the_real_token_is_accepted(bare, token):
    response = bare.get(
        "/api/commands/settings",
        params={"user_id": "u1"},
        headers={HEADER: token},
    )
    assert response.status_code == 200
    assert "enabled" in response.json()


def test_a_401_says_what_is_missing(bare):
    """The failure should be actionable, not a bare status code."""
    body = bare.get("/api/commands/settings", params={"user_id": "u1"}).json()
    assert "capability" in body["detail"].lower()


def test_the_schema_advertises_the_requirement():
    """The header is part of the contract, not a hidden detail."""
    schema = app.openapi()
    for path, method in (
        ("/api/commands/settings", "get"),
        ("/api/commands/settings", "put"),
        ("/api/commands/decide", "post"),
        ("/api/commands/pending", "get"),
    ):
        names = [
            parameter["name"]
            for parameter in schema["paths"][path][method].get("parameters", [])
        ]
        assert "x-pentagon-capability" in names, f"{method} {path}"


def test_secret_validation_errors_do_not_echo_rejected_input(bare, token):
    secret = "synthetic-secret-that-must-not-be-returned"
    response = bare.post(
        "/api/keys/validate",
        json={"api_key": secret},
        headers={HEADER: token},
    )
    assert response.status_code == 422
    assert secret not in response.text
    assert '"input"' not in response.text


def test_other_routes_are_not_gated_by_this(bare):
    """Only the authorising surface moves; the rest of the API is untouched."""
    assert bare.get("/openapi.json").status_code == 200


def test_every_api_route_advertises_the_capability_requirement():
    schema = app.openapi()
    api_operations = [
        (path, operation)
        for path, methods in schema["paths"].items()
        if path.startswith("/api/")
        for operation in methods.values()
    ]
    assert api_operations
    for path, operation in api_operations:
        names = [p["name"].lower() for p in operation.get("parameters", [])]
        assert "x-pentagon-capability" in names, f"{path} should be gated"


def test_ordinary_and_agent_endpoints_reject_missing_capability(bare):
    assert bare.get("/api/skills", params={"user_id": "u1"}).status_code == 401
    assert bare.get("/api/conversations", params={"user_id": "u1"}).status_code == 401
    assert bare.get("/api/audit-log", params={"user_id": "u1"}).status_code == 401
    assert bare.post(
        "/api/agent/decisions",
        json={"user_id": "u1", "turn_id": "turn", "call_ids": []},
    ).status_code == 401
