import json
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from app.config import settings
from app.db.models import ApiKey, Conversation, Message, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.security.crypto import encrypt_api_key
from app.services import chat_graph


MODEL_A = "nvidia/nemotron-3-super-120b-a12b"
MODEL_B = "nvidia/nemotron-3-nano-30b-a3b"


class FakeChatModel:
    def __init__(self):
        self.messages = []

    async def ainvoke(self, messages, config=None):
        self.messages = messages
        return AIMessage(content="Your earlier codeword was violet.")


@pytest.fixture
def model_setup(monkeypatch):
    initialize_database()
    user_id = f"model-test-{uuid4()}"
    conversation_id = str(uuid4())
    monkeypatch.setattr(settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode()))
    fake_model = FakeChatModel()
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_args, **_kwargs: fake_model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    monkeypatch.setattr(chat_graph, "search_web", _no_search)
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=encrypt_api_key("nvapi-test-model-key"),
                masked_key="nvapi-...key",
            )
        )
        conversation = Conversation(
            id=conversation_id,
            user_id=user_id,
            title="Model switch test",
            active_model=MODEL_A,
        )
        db.add(conversation)
        start = datetime.now(UTC)
        for index in range(8):
            role = "user" if index % 2 == 0 else "assistant"
            content = "EARLY_ONLY private detail" if index == 0 else f"Prior conversation message {index}."
            db.add(
                Message(
                    conversation_id=conversation_id,
                    role=role,
                    content=content,
                    model_used=MODEL_A,
                    created_at=start + timedelta(seconds=index),
                )
            )
        db.commit()
    setup = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "fake_model": fake_model,
    }
    yield setup
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        user = db.get(User, user_id)
        db.query(ApiKey).filter_by(user_id=user_id).delete(synchronize_session=False)
        if conversation is not None:
            db.delete(conversation)
        if user is not None:
            db.delete(user)
        db.commit()


async def _no_search(_query):
    raise AssertionError("web search should be disabled for this model test")


@pytest.fixture
def available_models(monkeypatch):
    async def list_models(_user_id, _api_key):
        return [
            {"id": MODEL_A},
            {"id": MODEL_B},
            {"id": "meta/llama-3.2-11b-vision-instruct"},
            {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"},
        ]

    monkeypatch.setattr("app.routes.chat.list_models_for_user", list_models)


def _metadata(response_text):
    for block in response_text.split("\n\n"):
        if block.startswith("event: metadata\n"):
            return json.loads(block.split("data: ", 1)[1])
    raise AssertionError("metadata event was not returned")


def test_switch_summarizes_once_and_reuses_summary_on_next_turn(
    model_setup, available_models, monkeypatch
):
    summary_calls = []

    async def summarize(_api_key, model, messages):
        summary_calls.append((model, len(messages)))
        return "The user established violet as the codeword and wants to continue the same project."

    monkeypatch.setattr("app.routes.chat.summarize_for_model_switch", summarize)
    with TestClient(app) as client:
        switched = client.patch(
            f"/api/conversations/{model_setup['conversation_id']}",
            json={"model": MODEL_B},
        )
        response = client.post(
            "/api/chat",
            json={
                "user_id": model_setup["user_id"],
                "conversation_id": model_setup["conversation_id"],
                "model": MODEL_B,
                "message": "What was the codeword?",
                "use_web_search": False,
            },
        )
        detail = client.get(f"/api/conversations/{model_setup['conversation_id']}")
        same_model = client.patch(
            f"/api/conversations/{model_setup['conversation_id']}",
            json={"model": MODEL_B},
        )

    assert switched.status_code == 200
    assert switched.json()["summary_generated"] is True
    assert switched.json()["summary_word_count"] < 200
    assert summary_calls == [(MODEL_B, 8)]
    assert response.status_code == 200
    trace = _metadata(response.text)["execution_trace"]["conversation_context"]
    assert trace == {
        "status": "summary_used",
        "summary_word_count": switched.json()["summary_word_count"],
        "raw_message_count": 6,
        "active_model": MODEL_B,
    }
    assert "violet" in response.text
    sent_messages = model_setup["fake_model"].messages
    assert sent_messages[0].type == "system"
    assert "violet" in sent_messages[0].content
    assert len(sent_messages) == 8  # summary + six prior messages + current context
    assert "EARLY_ONLY private detail" not in "\n".join(
        str(message.content) for message in sent_messages
    )
    assert detail.json()["active_model"] == MODEL_B
    assert detail.json()["summary_at_switch"] == (
        "The user established violet as the codeword and wants to continue the same project."
    )
    assert same_model.status_code == 200
    assert same_model.json()["summary_generated"] is False
    assert summary_calls == [(MODEL_B, 8)]


def test_failed_switch_summary_keeps_old_model(model_setup, available_models, monkeypatch):
    async def fail_summary(*_args, **_kwargs):
        raise TimeoutError("simulated model timeout")

    monkeypatch.setattr("app.routes.chat.summarize_for_model_switch", fail_summary)
    with TestClient(app) as client:
        response = client.patch(
            f"/api/conversations/{model_setup['conversation_id']}",
            json={"model": MODEL_B},
        )

    assert response.status_code == 502
    with SessionLocal() as db:
        conversation = db.get(Conversation, model_setup["conversation_id"])
        assert conversation.active_model == MODEL_A
        assert conversation.summary_at_switch is None


def test_chat_requires_patch_before_using_another_model(model_setup, monkeypatch):
    def graph_must_not_run(*_args, **_kwargs):
        raise AssertionError("chat graph ran before model switch")

    monkeypatch.setattr("app.routes.chat.build_chat_graph", graph_must_not_run)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "user_id": model_setup["user_id"],
                "conversation_id": model_setup["conversation_id"],
                "model": MODEL_B,
                "message": "Continue",
                "use_web_search": False,
            },
        )

    assert response.status_code == 409
    assert "PATCH /api/conversations/" in response.json()["detail"]


def test_models_endpoint_flags_vision_support(model_setup, monkeypatch):
    async def list_models(_user_id, _api_key):
        return [
            {"id": "meta/llama-3.2-11b-vision-instruct"},
            {"id": MODEL_A},
            {"id": "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"},
        ]

    monkeypatch.setattr("app.routes.models.list_models_for_user", list_models)
    with TestClient(app) as client:
        response = client.get("/api/models", params={"user_id": model_setup["user_id"]})

    assert response.status_code == 200
    models = {model["id"]: model for model in response.json()["models"]}
    assert models["meta/llama-3.2-11b-vision-instruct"]["supports_vision"] is True
    assert models[MODEL_A]["supports_vision"] is False
    assert models["nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"]["supports_vision"] is True
