import hashlib
import io
import math
import re
from uuid import uuid4

from cryptography.fernet import Fernet
from pydantic import SecretStr
from reportlab.pdfgen import canvas
from fastapi.testclient import TestClient

from app.config import settings
from app.db.models import ApiKey, Conversation, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.security.crypto import encrypt_api_key
from app.services import chat_graph, document_store


CONTENT = (
    "Project Zephyr uses a cobalt rotor and a 17-stage pressure valve. "
    "The maintenance interval is 82 days."
)


def _pdf_bytes(text: str) -> bytes:
    buffer = io.BytesIO()
    page = canvas.Canvas(buffer)
    page.drawString(50, 760, text)
    page.save()
    return buffer.getvalue()


def _hash_embeddings(texts: list[str]) -> list[list[float]]:
    vectors = []
    for text in texts:
        vector = [0.0] * 64
        for token in re.findall(r"[a-z0-9]+", text.lower()):
            digest = hashlib.sha256(token.encode()).digest()
            vector[int.from_bytes(digest[:4], "big") % len(vector)] += 1.0
        norm = math.sqrt(sum(value * value for value in vector)) or 1.0
        vectors.append([value / norm for value in vector])
    return vectors


class FakeChatModel:
    def __init__(self):
        self.messages = []

    async def ainvoke(self, messages, config=None):
        self.messages = messages
        from langchain_core.messages import AIMessage

        return AIMessage(content="Project Zephyr uses a cobalt rotor.")


def test_pdf_upload_chunks_are_retrieved_by_followup_chat(monkeypatch, tmp_path):
    initialize_database()
    user_id = f"docs-test-{uuid4()}"
    monkeypatch.setattr(settings, "chroma_persist_directory", str(tmp_path / "chroma"))
    monkeypatch.setattr(settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode()))
    document_store._client.cache_clear()

    async def fake_provider(_user_id, _api_key):
        return "local:test-hash-embeddings"

    async def fake_embeddings(texts, _provider, _api_key, _input_type):
        return _hash_embeddings(texts)

    monkeypatch.setattr(document_store, "choose_embedding_provider", fake_provider)
    monkeypatch.setattr(document_store, "embed_texts", fake_embeddings)
    fake_model = FakeChatModel()
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_args, **_kwargs: fake_model)
    monkeypatch.setattr(chat_graph, "search_web", _no_search)

    try:
        with SessionLocal() as db:
            db.add(User(id=user_id))
            db.add(
                ApiKey(
                    user_id=user_id,
                    encrypted_key=encrypt_api_key("nvapi-test-document-key"),
                    masked_key="nvapi-...t-key",
                )
            )
            db.commit()

        with TestClient(app) as client:
            created = client.post(
                "/api/conversations",
                json={"user_id": user_id, "title": "Zephyr manual"},
            )
            assert created.status_code == 201
            conversation_id = created.json()["id"]

            uploaded = client.post(
                "/api/documents/upload",
                data={"user_id": user_id, "conversation_id": conversation_id},
                files={"file": ("zephyr.pdf", _pdf_bytes(CONTENT), "application/pdf")},
            )
            assert uploaded.status_code == 201, uploaded.text
            upload_result = uploaded.json()
            assert upload_result["chunks_stored"] >= 1

            chat_response = client.post(
                "/api/chat",
                json={
                    "user_id": user_id,
                    "conversation_id": conversation_id,
                    "model": "test-model",
                    "message": "What does Project Zephyr use?",
                    "use_web_search": False,
                },
            )
            assert chat_response.status_code == 200
            assert "event: metadata" in chat_response.text
            assert '"status":"ran"' in chat_response.text
            assert '"filename":"zephyr.pdf"' in chat_response.text
            assert "cobalt rotor" in fake_model.messages[-1].content.lower()

            deleted = client.delete(
                f"/api/documents/{upload_result['document_id']}",
                params={"user_id": user_id},
            )
            assert deleted.status_code == 200
            listed = client.get(
                "/api/documents",
                params={"user_id": user_id, "conversation_id": conversation_id},
            )
            assert listed.status_code == 200
            assert listed.json() == []

            with SessionLocal() as db:
                conversation = db.get(Conversation, conversation_id)
                user = db.get(User, user_id)
                db.query(ApiKey).filter(ApiKey.user_id == user_id).delete(
                    synchronize_session=False
                )
                if conversation is not None:
                    db.delete(conversation)
                if user is not None:
                    db.delete(user)
                db.commit()
    finally:
        document_store._client.cache_clear()


async def _no_search(_query: str):
    raise AssertionError("web search should be disabled for this document retrieval test")
