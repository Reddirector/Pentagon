"""Traces are diagnostics: they must persist, and they must never leak secrets."""

from uuid import uuid4

from sqlalchemy import select

from app.agent.traces import TraceRecorder, redact_args
from app.db.models import Conversation, ToolTrace, User
from app.db.session import SessionLocal


def test_redact_args_masks_secret_shaped_keys():
    redacted = redact_args(
        {
            "api_key": "nvapi-123",
            "Authorization": "Bearer x",
            "token": "abc",
            "password": "hunter2",
            "query": "weather in pune",
        }
    )
    assert redacted["api_key"] == "[redacted]"
    assert redacted["Authorization"] == "[redacted]"
    assert redacted["token"] == "[redacted]"
    assert redacted["password"] == "[redacted]"
    assert redacted["query"] == "weather in pune"


def test_redact_args_truncates_long_values():
    redacted = redact_args({"code": "x" * 900})
    assert redacted["code"].startswith("x" * 200)
    assert "[900 chars total]" in redacted["code"]


def test_recorder_writes_rows_owned_by_the_user():
    user_id = f"trace-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=user_id))
        conversation = Conversation(user_id=user_id, title="Trace test")
        db.add(conversation)
        db.commit()
        conversation_id = conversation.id

    recorder = TraceRecorder(user_id, conversation_id, turn_id=str(uuid4()))
    recorder.record_tool_call(
        0, "web_search", {"query": "pune weather", "api_key": "secret"}, "ok", duration_ms=41.4
    )
    recorder.record_tool_call(1, "calculator", {"expression": "2+2"}, "error")
    assert recorder.flush() == 2

    with SessionLocal() as db:
        rows = db.scalars(
            select(ToolTrace).where(ToolTrace.user_id == user_id).order_by(ToolTrace.step)
        ).all()

    assert [row.tool for row in rows] == ["web_search", "calculator"]
    assert rows[0].status == "ok"
    assert rows[0].duration_ms == 41
    assert rows[0].args_redacted["api_key"] == "[redacted]"
    assert rows[0].args_redacted["query"] == "pune weather"
    assert rows[1].status == "error"


def test_flush_with_nothing_buffered_is_a_no_op():
    recorder = TraceRecorder("u", "c", "t")
    assert recorder.flush() == 0
