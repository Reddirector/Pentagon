"""Rotating KEY_ENCRYPTION_SECRET must degrade gracefully, not return a 500.

A stored key is encrypted with the server secret, so rotating that secret makes
every existing key undecryptable. Routes that only handled "no key stored"
turned that into a bare Internal Server Error, leaving the app unusable with no
way for the user to recover short of guessing.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.config import settings
from app.db.models import ApiKey, Conversation, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.services.nvidia_client import KeyValidationResult, clear_models_cache


@pytest.fixture
def user_with_undecryptable_key(monkeypatch):
    """A user whose stored key was encrypted under a previous server secret."""
    initialize_database()
    user_id = f"rotated-secret-{uuid4()}"
    monkeypatch.setattr(settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode()))

    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=Fernet(Fernet.generate_key()).encrypt(b"nvapi-old-secret").decode(),
                masked_key="nvapi-...cret",
            )
        )
        db.commit()

    yield user_id

    with SessionLocal() as db:
        db.query(ApiKey).filter(ApiKey.user_id == user_id).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.user_id == user_id).delete(synchronize_session=False)
        db.query(User).filter(User.id == user_id).delete(synchronize_session=False)
        db.commit()


def test_models_endpoint_explains_an_undecryptable_key(user_with_undecryptable_key):
    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get("/api/models", params={"user_id": user_with_undecryptable_key})

    assert response.status_code == 500
    assert "could not be decrypted" in response.json()["detail"]


def test_chat_endpoint_explains_an_undecryptable_key(user_with_undecryptable_key):
    user_id = user_with_undecryptable_key
    with SessionLocal() as db:
        conversation = Conversation(id=str(uuid4()), user_id=user_id, title="Rotated")
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "model": "test-model",
                "message": "Hello?",
            },
        )

    assert response.status_code == 500
    assert "could not be decrypted" in response.json()["detail"]


def test_missing_key_still_reports_a_plain_404(monkeypatch):
    """The helper must not change the well-handled "no key" path."""
    initialize_database()
    user_id = f"no-key-{uuid4()}"
    monkeypatch.setattr(settings, "nvidia_server_api_key", None)

    with TestClient(app) as client:
        response = client.get("/api/models", params={"user_id": user_id})

    assert response.status_code == 404
    assert response.json()["detail"] == "No API key is stored for this user."


def test_replacing_the_nvidia_key_masks_it_and_refreshes_the_model_cache(monkeypatch):
    """A rotated key is the next key used, with no raw-key response field."""
    from app.services import nvidia_client

    initialize_database()
    user_id = f"key-replacement-{uuid4()}"
    seen_keys: list[str] = []

    async def valid_key(_raw_key: str) -> KeyValidationResult:
        return KeyValidationResult(valid=True, model_count=1, sample_models=("model",))

    async def fake_models(api_key: str):
        seen_keys.append(api_key)
        return [{"id": f"model-for-{api_key[-4:]}"}]

    monkeypatch.setattr("app.routes.keys.validate_api_key", valid_key)
    monkeypatch.setattr(nvidia_client, "_request_models", fake_models)
    clear_models_cache(user_id)

    with TestClient(app) as client:
        first = client.post(
            "/api/keys",
            json={"user_id": user_id, "api_key": "nvapi-old-fake-key-1111"},
        )
        assert first.status_code == 200, first.text
        assert first.json()["masked_key"] == "nvapi-...1111"
        assert "nvapi-old-fake-key-1111" not in first.text
        old_models = client.get(f"/api/models?user_id={user_id}")
        assert old_models.status_code == 200
        assert old_models.json()["models"][0]["id"] == "model-for-1111"

        second = client.post(
            "/api/keys",
            json={"user_id": user_id, "api_key": "nvapi-new-fake-key-2222"},
        )
        assert second.status_code == 200, second.text
        assert second.json()["masked_key"] == "nvapi-...2222"
        assert "nvapi-new-fake-key-2222" not in second.text
        new_models = client.get(f"/api/models?user_id={user_id}")
        assert new_models.status_code == 200
        assert new_models.json()["models"][0]["id"] == "model-for-2222"

    assert seen_keys == ["nvapi-old-fake-key-1111", "nvapi-new-fake-key-2222"]
