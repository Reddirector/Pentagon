import json
import subprocess
from uuid import uuid4

import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from pydantic import SecretStr

from app.config import settings
from app.db.models import ApiKey, Conversation, User
from app.db.session import SessionLocal, initialize_database
from app.main import app
from app.security.crypto import encrypt_api_key
from app.services import chat_graph, image_inputs
from app.services.video import MAX_VIDEO_BYTES, PreparedVideo, VIDEO_MODEL_ID


class FakeChatModel:
    def __init__(self):
        self.messages = []

    async def ainvoke(self, messages, config=None):
        self.messages = messages
        return AIMessage(content="At 0 seconds the scene is red, then it changes to blue.")


@pytest.fixture
def video_setup(monkeypatch, tmp_path):
    initialize_database()
    user_id = f"video-test-{uuid4()}"
    conversation_id = str(uuid4())
    monkeypatch.setattr(settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode()))
    fake_model = FakeChatModel()
    monkeypatch.setattr(chat_graph, "make_chat_model", lambda *_args, **_kwargs: fake_model)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    monkeypatch.setattr(chat_graph, "search_web", _no_search)
    monkeypatch.setattr(chat_graph, "analyze_video", _describe_video)
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=encrypt_api_key("nvapi-test-video-key"),
                masked_key="nvapi-...key",
            )
        )
        db.add(Conversation(id=conversation_id, user_id=user_id, title="Video test"))
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


async def _describe_video(_api_key, _question, _video_data_uri, *, image_data_uri=None):
    return "At 0 seconds the scene is red, then it changes to blue at 1 second."


async def _no_search(_query):
    raise AssertionError("web search should be disabled for this video test")


async def _prepared_video(_upload):
    return PreparedVideo(
        data_uri="data:video/mp4;base64,dGVzdA==",
        duration_seconds=2.0,
        fps=1.0,
        frames_sent=2,
    )


def _form(setup, *, message="Describe the distinct moments with timestamps."):
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


def test_video_runs_native_vision_branch_and_reports_frames(video_setup, monkeypatch):
    monkeypatch.setattr(image_inputs, "read_uploaded_video", _prepared_video)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            data=_form(video_setup),
            files={"video": ("clip.mp4", b"test video", "video/mp4")},
        )

    assert response.status_code == 200
    metadata = _metadata(response.text)
    trace = metadata["execution_trace"]["vision_analysis"]
    assert trace["status"] == "ran"
    assert trace["path"] == "native_video_model"
    assert trace["model_used"] == VIDEO_MODEL_ID
    assert trace["frames_sent"] == 2
    assert trace["sampling_fps"] == 1.0
    assert metadata["sources_used"]["video"]["frames_sent"] == 2
    assert metadata["sources_used"]["video"]["model_used"] == VIDEO_MODEL_ID
    assert "At 0 seconds" in response.text
    assert "[Video analysis:" in video_setup["fake_model"].messages[-1].content


def test_video_and_retrieval_branches_merge(video_setup, monkeypatch):
    monkeypatch.setattr(image_inputs, "read_uploaded_video", _prepared_video)
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: True)

    async def retrieve(**_kwargs):
        return [{
            "chunk_id": "chunk-1",
            "document_id": "doc-1",
            "filename": "reference.txt",
            "content": "The recording is a color calibration sequence.",
        }]

    monkeypatch.setattr(chat_graph, "retrieve_chunks", retrieve)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            data=_form(video_setup, message="Compare this clip to the uploaded reference."),
            files={"video": ("clip.mp4", b"test video", "video/mp4")},
        )

    assert response.status_code == 200
    metadata = _metadata(response.text)
    trace = metadata["execution_trace"]
    assert trace["vision_analysis"]["status"] == "ran"
    assert trace["retrieve_documents"]["status"] == "ran"
    assert "color calibration sequence" in video_setup["fake_model"].messages[-1].content
    assert "[Video analysis:" in video_setup["fake_model"].messages[-1].content


@pytest.mark.parametrize(
    "filename,content,content_type,detail",
    [
        ("large.mp4", b"x" * (MAX_VIDEO_BYTES + 1), "video/mp4", f"{MAX_VIDEO_BYTES // (1024 * 1024)} MB"),
        ("clip.gif", b"GIF89a", "video/gif", "mp4, mov, webm, mkv, or avi"),
    ],
)
def test_invalid_video_does_not_invoke_graph(
    video_setup, monkeypatch, filename, content, content_type, detail
):
    def graph_must_not_run(*_args, **_kwargs):
        raise AssertionError("invalid video reached the LangGraph pipeline")

    monkeypatch.setattr("app.routes.chat.build_chat_graph", graph_must_not_run)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            data=_form(video_setup),
            files={"video": (filename, content, content_type)},
        )

    assert response.status_code == 400
    assert detail in response.json()["detail"]


def test_video_longer_than_limit_is_rejected_before_graph(video_setup, tmp_path, monkeypatch):
    clip = tmp_path / "long.mp4"
    subprocess.run(
        [
            "ffmpeg", "-hide_banner", "-loglevel", "error", "-y",
            "-f", "lavfi", "-i", f"color=c=red:s=16x16:r=1:d={int(settings.video_max_duration_seconds) + 1}",
            "-c:v", "libx264", "-pix_fmt", "yuv420p", str(clip),
        ],
        check=True,
    )

    def graph_must_not_run(*_args, **_kwargs):
        raise AssertionError("overlong video reached the LangGraph pipeline")

    monkeypatch.setattr("app.routes.chat.build_chat_graph", graph_must_not_run)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            data=_form(video_setup),
            files={"video": ("long.mp4", clip.read_bytes(), "video/mp4")},
        )

    assert response.status_code == 400
    assert f"{int(settings.video_max_duration_seconds)} seconds or shorter" in response.json()["detail"]


def test_video_analysis_failure_does_not_stop_chat(video_setup, monkeypatch):
    async def failed_video(*_args, **_kwargs):
        raise TimeoutError("simulated timeout")

    monkeypatch.setattr(image_inputs, "read_uploaded_video", _prepared_video)
    monkeypatch.setattr(chat_graph, "analyze_video", failed_video)
    with TestClient(app) as client:
        response = client.post(
            "/api/chat",
            data=_form(video_setup),
            files={"video": ("clip.mp4", b"test video", "video/mp4")},
        )

    assert response.status_code == 200
    trace = _metadata(response.text)["execution_trace"]["vision_analysis"]
    assert trace["status"] == "failed"
    assert trace["error"] == "TimeoutError"
    assert "At 0 seconds" in response.text


def test_configured_size_can_lower_the_cap_but_never_raise_it(monkeypatch):
    """The deployment setting is a ceiling, not a switch that removes the bound."""
    from app.services import video

    monkeypatch.setattr(settings, "video_max_bytes", 8 * 1024 * 1024)
    assert video.max_bytes_limit() == 8 * 1024 * 1024

    monkeypatch.setattr(settings, "video_max_bytes", 10 * 1024 * 1024 * 1024)
    assert video.max_bytes_limit() == video.MAX_VIDEO_BYTES

    monkeypatch.setattr(settings, "video_max_bytes", 0)
    assert video.max_bytes_limit() == video.MAX_VIDEO_BYTES
