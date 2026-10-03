from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import settings
from app.db.models import ApiKey, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.security.crypto import encrypt_api_key
from app.security.keys import NoKeyAvailableError, resolve_api_key


@pytest.fixture
def api_client():
    initialize_database()
    with TestClient(app) as client:
        yield client


def test_stored_key_takes_precedence_over_server_key(monkeypatch):
    initialize_database()
    monkeypatch.setattr(
        settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode())
    )
    monkeypatch.setattr(
        settings, "nvidia_server_api_key", SecretStr("nvapi-server-fallback")
    )
    user_id = f"resolver-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=encrypt_api_key("nvapi-stored-key"),
                masked_key="nvapi-...tored",
            )
        )
        db.commit()
        assert resolve_api_key(db, user_id) == "nvapi-stored-key"


def test_server_fallback_used_when_no_stored_key(monkeypatch):
    initialize_database()
    monkeypatch.setattr(
        settings, "nvidia_server_api_key", SecretStr("nvapi-server-fallback")
    )
    user_id = f"resolver-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.commit()
        assert resolve_api_key(db, user_id) == "nvapi-server-fallback"


def test_no_key_available_when_neither_source_set(monkeypatch):
    initialize_database()
    monkeypatch.setattr(settings, "nvidia_server_api_key", None)
    with SessionLocal() as db:
        with pytest.raises(NoKeyAvailableError):
            resolve_api_key(db, f"resolver-{uuid4()}")


def test_models_response_includes_default_model(
    api_client, monkeypatch
):
    monkeypatch.setattr(settings, "default_chat_model", "z-ai/glm-5.3-flash")
    monkeypatch.setattr(
        settings, "nvidia_server_api_key", SecretStr("nvapi-server-fallback")
    )

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.headers["authorization"] == "Bearer nvapi-server-fallback"
        return httpx.Response(
            200,
            json={"data": [{"id": "z-ai/glm-5.3-flash"}, {"id": "other-model"}]},
            request=request,
        )

    monkeypatch.setattr(
        "app.services.nvidia_client._new_async_client",
        lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )
    response = api_client.get(f"/api/models?user_id=fallback-models-{uuid4()}")

    assert response.status_code == 200
    body = response.json()
    assert body["default_model"] == "z-ai/glm-5.3-flash"
    assert [model["id"] for model in body["models"]] == [
        "z-ai/glm-5.3-flash",
        "other-model",
    ]
    assert "nvapi-server-fallback" not in response.text
