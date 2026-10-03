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