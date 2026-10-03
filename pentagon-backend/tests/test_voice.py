import base64
import json
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessageChunk
from pydantic import SecretStr

from app.config import settings
from app.db.models import ApiKey, Conversation, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.security.crypto import encrypt_api_key
from app.services.speech import AudioChunk


@pytest.fixture
def voice_setup(monkeypatch):
    initialize_database()
    user_id = f"voice-test-{uuid4()}"
    conversation_id = str(uuid4())
    monkeypatch.setattr(settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode()))
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=encrypt_api_key("nvapi-test-voice-key"),
                masked_key="nvapi-...key",
            )
        )
        db.add(Conversation(id=conversation_id, user_id=user_id, title="Voice test"))
        db.commit()
    yield {"user_id": user_id, "conversation_id": conversation_id}
    with SessionLocal() as db:
        conversation = db.get(Conversation, conversation_id)
        user = db.get(User, user_id)
        db.query(ApiKey).filter(ApiKey.user_id == user_id).delete(synchronize_session=False)
        if conversation is not None:
            db.delete(conversation)
        if user is not None:
            db.delete(user)
        db.commit()


def _sse_events(response_text):
    events = []
    for block in response_text.split("\n\n"):
        if block.startswith("event: "):
            event, data = block.split("\ndata: ", 1)
            events.append((event.removeprefix("event: "), json.loads(data)))
    return events


def test_transcribe_returns_text_and_timing(voice_setup, monkeypatch):
    async def fake_transcribe(_content, filename, _api_key):
        assert filename == "question.webm"
        return "How does this work?", "faster-whisper:base"

    monkeypatch.setattr("app.routes.voice.transcribe_audio", fake_transcribe)
    with TestClient(app) as client:
        response = client.post(
            "/api/voice/transcribe",
            data={"user_id": voice_setup["user_id"]},
            files={"file": ("question.webm", b"fake audio bytes", "audio/webm")},
        )

    assert response.status_code == 200
    body = response.json()
    assert body["text"] == "How does this work?"
    trace = body["execution_trace"]["transcription"]
    assert trace["status"] == "ran"
    assert trace["duration_ms"] >= 0
    assert trace["provider"] == "faster-whisper:base"


def test_silence_returns_empty_transcript_and_chat_rejects_it(voice_setup, monkeypatch):
    async def silent_transcribe(*_args):
        return "  ", "faster-whisper:base"

    def graph_must_not_run(*_args, **_kwargs):
        raise AssertionError("empty voice transcript reached the chat graph")

    monkeypatch.setattr("app.routes.voice.transcribe_audio", silent_transcribe)
    monkeypatch.setattr("app.routes.chat.build_chat_graph", graph_must_not_run)
    with TestClient(app) as client:
        transcription = client.post(
            "/api/voice/transcribe",
            data={"user_id": voice_setup["user_id"]},
            files={"file": ("silence.wav", b"valid-shaped-for-mock", "audio/wav")},
        )
        chat = client.post(
            "/api/chat",
            json={
                "user_id": voice_setup["user_id"],
                "conversation_id": voice_setup["conversation_id"],
                "model": "test-model",
                "message": transcription.json()["text"],
            },
        )

    assert transcription.status_code == 200
    assert transcription.json()["text"] == ""
    assert transcription.json()["execution_trace"]["transcription"]["status"] == "empty"
    assert chat.status_code == 422
    assert "message is required" in chat.json()["detail"]


def test_synthesize_endpoint_streams_raw_pcm(monkeypatch):
    async def fake_speech(_text, _voice, _api_key):
        yield AudioChunk(b"\x01\x00\x02\x00", 22050, 1, 2, "piper:test")

    monkeypatch.setattr("app.routes.voice.stream_speech", fake_speech)
    with TestClient(app) as client:
        response = client.post("/api/voice/synthesize", json={"text": "Speak this."})

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("audio/pcm")
    assert response.headers["x-audio-format"] == "pcm_s16le"
    assert response.content == b"\x01\x00\x02\x00"


def test_chat_audio_follows_text_and_reports_all_stage_timings(voice_setup, monkeypatch):
    class FakeGraph:
        async def astream(self, graph_input, **_kwargs):
            yield {
                "type": "messages",
                "data": (AIMessageChunk(content="Hello there."), {}),
            }
            yield {
                "type": "values",
                "data": {
                    "answer": "Hello there.",
                    "execution_trace": {
                        **graph_input["execution_trace"],
                        "generate_response": {"status": "ran", "duration_ms": 3},
                    },
                    "web_results": [],
                    "retrieved_chunks": [],
                    "vision_result": [],
                },
            }

    async def fake_speech(_text, _voice, _api_key):
        yield AudioChunk(b"\x01\x00\x02\x00", 22050, 1, 2, "piper:en_US-lessac-medium")

    monkeypatch.setattr("app.routes.chat.build_chat_graph", lambda *_args, **_kwargs: FakeGraph())
    monkeypatch.setattr("app.routes.chat.stream_speech", fake_speech)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            json={
                "user_id": voice_setup["user_id"],
                "conversation_id": voice_setup["conversation_id"],
                "model": "test-model",
                "message": "Hello",
                "respond_with_audio": True,
                "transcription_duration_ms": 27.5,
                "transcription_provider": "faster-whisper:base",
            },
        )

    events = _sse_events(response.text)
    event_names = [event for event, _data in events]
    assert response.status_code == 200
    assert event_names.index("token") < event_names.index("audio_chunk")
    assert event_names.index("audio_chunk") < event_names.index("metadata")
    audio_chunk = next(data for event, data in events if event == "audio_chunk")
    assert base64.b64decode(audio_chunk["content"]) == b"\x01\x00\x02\x00"
    metadata = next(data for event, data in events if event == "metadata")
    trace = metadata["execution_trace"]
    assert trace["transcription"]["duration_ms"] == 27.5
    assert trace["transcription"]["provider"] == "faster-whisper:base"
    assert trace["generate_response"]["time_to_first_token_ms"] >= 0
    assert trace["synthesis"]["time_to_first_audio_ms"] >= 0
    assert trace["synthesis"]["provider"] == "piper:en_US-lessac-medium"
    assert "event: done" in response.text
