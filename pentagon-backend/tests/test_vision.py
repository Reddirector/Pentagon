import base64
import io
import json
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr
from PIL import Image

from app.config import settings
from app.db.models import ApiKey, Conversation, Message, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.security.crypto import encrypt_api_key
from app.services import chat_graph
from app.services.vision import VISION_MODEL_ID


def _png_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (2, 2), color=(210, 35, 50)).save(buffer, format="PNG")
    return buffer.getvalue()


class FakeChatModel:
    def __init__(self):
        self.messages = []

    async def ainvoke(self, messages, config=None):
        self.messages = messages
        return AIMessage(content="The image shows a red object.")


@pytest.fixture
def chat_setup(monkeypatch, tmp_path):
    initialize_database()
    user_id = f"vision-test-{uuid4()}"
    conversation_id = str(uuid4())
    monkeypatch.setattr(settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode()))
    monkeypatch.setattr(settings, "image_upload_directory", str(tmp_path / "image_uploads"))
    fake_model = FakeChatModel()
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_args, **_kwargs: fake_model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    monkeypatch.setattr(chat_graph, "search_web", _no_search)
    monkeypatch.setattr(
        chat_graph,
        "analyze_image",
        _describe_image,
    )
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=encrypt_api_key("nvapi-test-vision-key"),
                masked_key="nvapi-...key",
            )
        )
        db.add(Conversation(id=conversation_id, user_id=user_id, title="Vision test"))
        db.commit()
    setup = {
        "user_id": user_id,
        "conversation_id": conversation_id,
        "fake_model": fake_model,
        "tmp_path": tmp_path,
    }
    yield setup
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        user = db.get(User, user_id)
        db.query(ApiKey).filter(ApiKey.user_id == user_id).delete(synchronize_session=False)
        if conversation is not None:
            db.delete(conversation)
        if user is not None:
            db.delete(user)
        db.commit()


async def _describe_image(_api_key, _question, _image_data_uri):
    return "A small red square is visible."


async def _no_search(_query):
    raise AssertionError("web search should be disabled for this vision test")


def _chat_form(setup, *, message="What is in this picture?"):
    return {
        "user_id": setup["user_id"],
        "conversation_id": setup["conversation_id"],
        "model": "test-model",
        "message": message,
        "use_web_search": "false",
    }


def _metadata(response_text):
    for block in response_text.split("\n\n"):
        if block.startswith("event: metadata\n"):
            return json.loads(block.split("data: ", 1)[1])
    raise AssertionError("metadata event was not returned")


def test_valid_multipart_image_runs_vision_and_stores_a_path(chat_setup):
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            data=_chat_form(chat_setup),
            files={"image": ("photo.png", _png_bytes(), "image/png")},
        )

    assert response.status_code == 200
    metadata = _metadata(response.text)
    vision = metadata["execution_trace"]["vision_analysis"]
    assert vision["ran"] is True
    assert vision["model_used"] == VISION_MODEL_ID
    assert vision["duration_ms"] >= 0
    assert metadata["sources_used"]["image"] == {
        "model_used": VISION_MODEL_ID,
        "description_summary": "A small red square is visible.",
    }
    assert "event: done" in response.text
    with SessionLocal() as db:
        message = db.query(Message).filter_by(
            conversation_id=chat_setup["conversation_id"], role="user"
        ).one()
        assert message.image_path.endswith(f"{message.id}.png")
        with open(message.image_path, "rb") as image_file:
            assert image_file.read() == _png_bytes()


def test_base64_data_uri_image_only_uses_default_question(chat_setup):
    image = base64.b64encode(_png_bytes()).decode("ascii")
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "user_id": chat_setup["user_id"],
                "conversation_id": chat_setup["conversation_id"],
                "model": "test-model",
                "message": "",
                "image": f"data:image/png;base64,{image}",
                "use_web_search": False,
            },
        )

    assert response.status_code == 200
    assert "event: done" in response.text
    assert "Describe what's in this image." in chat_setup["fake_model"].messages[-1].content


@pytest.mark.parametrize(
    "filename,content,content_type,detail",
    [
        ("large.png", b"x" * (10 * 1024 * 1024), "image/png", "smaller than 10 MB"),
        ("animation.gif", b"GIF89a", "image/gif", "jpg, png, or webp"),
    ],
)
def test_rejected_image_does_not_invoke_graph(
    chat_setup, monkeypatch, filename, content, content_type, detail
):
    def graph_must_not_run(*_args, **_kwargs):
        raise AssertionError("invalid image reached the LangGraph pipeline")

    monkeypatch.setattr("app.routes.chat.build_chat_graph", graph_must_not_run)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            data=_chat_form(chat_setup),
            files={"image": (filename, content, content_type)},
        )

    assert response.status_code == 400
    assert detail in response.json()["detail"]


def test_vision_failure_keeps_chat_response_alive(chat_setup, monkeypatch):
    async def failed_vision(*_args, **_kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(chat_graph, "analyze_image", failed_vision)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            data=_chat_form(chat_setup),
            files={"image": ("photo.png", _png_bytes(), "image/png")},
        )

    assert response.status_code == 200
    metadata = _metadata(response.text)
    assert metadata["execution_trace"]["vision_analysis"]["status"] == "failed"
    assert metadata["execution_trace"]["vision_analysis"]["error"] == "TimeoutError"
    assert "The image shows a red object." in response.text
    assert "event: done" in response.text


def test_image_and_retrieval_branches_merge_into_one_response(chat_setup, monkeypatch):
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: True)

    async def retrieve(**_kwargs):
        return [
            {
                "chunk_id": "chunk-1",
                "document_id": "doc-1",
                "filename": "reference.txt",
                "content": "The reference object is a red square.",
            }
        ]

    monkeypatch.setattr(chat_graph, "retrieve_chunks", retrieve)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            data=_chat_form(chat_setup, message="Does this match the uploaded reference?"),
            files={"image": ("photo.png", _png_bytes(), "image/png")},
        )

    assert response.status_code == 200
    metadata = _metadata(response.text)
    trace = metadata["execution_trace"]
    assert trace["vision_analysis"]["status"] == "ran"
    assert trace["retrieve_documents"]["status"] == "ran"
    assert metadata["sources_used"]["documents"][0]["filename"] == "reference.txt"
    prompt = chat_setup["fake_model"].messages[-1].content
    assert "The reference object is a red square." in prompt
    assert "[Image description: A small red square is visible.]" in prompt
