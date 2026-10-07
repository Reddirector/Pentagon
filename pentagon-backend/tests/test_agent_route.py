"""T13: the agent turn surface -- events over the wire, gates, honest endings.

The loop already proved itself turn by turn; what is under test here is the
*surface*: that every event reaches an SSE client under its own name, that an
approval card or question can be answered while the turn is still open, that
Stop (a disconnect) cleans the session instead of leaking it, that a retry
does not store the question twice, and that badges are read from cache and
never from the network.
"""

import asyncio

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient

from app.agent.loop import TurnRequest
from app.db.models import (
    Conversation,
    Memory,
    Message,
    ModelCapabilities,
    ToolTrace,
    User,
)
from app.db.session import SessionLocal
from app.evals.mock_llm import MockLLM, ScriptedTurn
from app.main import app
from app.routes import agent

USER = "agent-route"
CONVERSATION = "conv-agent"
MODEL = "test-model"


def _reset_rows() -> None:
    """A clean slate around every test: rows, traces, memories, the seed."""
    agent._SESSIONS.clear()
    with SessionLocal() as db:
        db.query(ToolTrace).filter(ToolTrace.user_id == USER).delete()
        db.query(Memory).filter(Memory.user_id == USER).delete()
        db.query(Message).filter(Message.conversation_id == CONVERSATION).delete()
        db.query(ModelCapabilities).filter(
            ModelCapabilities.model_id == MODEL
        ).delete()
        db.query(Conversation).filter(Conversation.id == CONVERSATION).delete()
        db.query(User).filter(User.id == USER).delete()
        db.commit()


@pytest.fixture(autouse=True)
def _turn_rows():
    """A user and conversation to own the turn, and a seeded capability row.

    The seed is the important half: without it the loop's first turn would
    probe the real endpoint, and a test must never spend a request.
    """
    _reset_rows()
    with SessionLocal() as db:
        db.add(User(id=USER))
        db.add(Conversation(id=CONVERSATION, user_id=USER, title="Agent"))
        db.add(
            ModelCapabilities(
                model_id=MODEL, native_tools=True, parallel_tools=True
            )
        )
        db.commit()
    yield
    _reset_rows()


def _hermetic(monkeypatch) -> None:
    """No network, no key, no cached registry: each test builds its own."""
    monkeypatch.setattr(
        agent, "resolve_api_key_or_http", lambda *_a, **_k: "nvapi-test"
    )
    monkeypatch.setattr(agent, "_REGISTRY", None)


def _turn(turn_id: str, message: str, level: int = 2) -> TurnRequest:
    return TurnRequest(
        user_id=USER,
        conversation_id=CONVERSATION,
        turn_id=turn_id,
        permission_level=level,
        user_message=message,
        model_id=MODEL,
    )


def test_agent_turn_streams_every_event_and_persists(monkeypatch):
    _hermetic(monkeypatch)
    monkeypatch.setattr(
        agent,
        "make_chat_model",
        lambda *_a, **_k: MockLLM(
            [
                ScriptedTurn(
                    tool_calls=(
                        {
                            "name": "calculator",
                            "args": {"expression": "6*7"},
                            "id": "c1",
                        },
                    )
                ),
                ScriptedTurn(text="The answer is 42."),
            ]
        ),
    )

    with TestClient(app) as client:
        response = client.post(
            "/api/agent/chat",
            json={
                "user_id": USER,
                "conversation_id": CONVERSATION,
                "model": MODEL,
                "message": "What is 6 times 7?",
            },
        )

    assert response.status_code == 200
    body = response.text
    # The wire vocabulary the client renders: identity (with the turn id the
    # decision routes need), streaming, the tool round trip, and the verdict.
    assert "event: conversation" in body
    assert '"turn_id"' in body
    assert "event: token" in body
    assert "event: tool_start" in body
    assert "event: tool_result" in body
    assert '"tool":"calculator"' in body
    assert "event: done" in body

    with SessionLocal() as db:
        rows = list(
            db.query(Message).filter(Message.conversation_id == CONVERSATION).all()
        )
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[1].content == "The answer is 42."
    # The session is gone the moment the turn ends: a decision arriving
    # later must find nothing rather than a gate nobody is listening to.
    assert agent._SESSIONS == {}


def test_approval_card_can_be_answered_while_the_turn_is_open(monkeypatch):
    _hermetic(monkeypatch)
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {
                        "name": "remember",
                        "args": {"text": "Prefers metric units.", "label": "units"},
                        "id": "m1",
                    },
                )
            ),
            ScriptedTurn(text="Saved."),
        ]
    )

    async def scenario():
        session = agent._register(
            agent._TurnSession(turn_id="t-approval", user_id=USER)
        )
        chunks: list[str] = []

        async def consume():
            async for chunk in agent._stream_agent(
                turn=_turn("t-approval", "Remember my units."),
                model=model,
                session=session,
                model_id=MODEL,
            ):
                chunks.append(chunk)

        consumer = asyncio.ensure_future(consume())
        for _ in range(250):
            await asyncio.sleep(0.02)
            if any("approval_required" in chunk for chunk in chunks):
                break
        assert any("approval_required" in chunk for chunk in chunks), (
            "the approval card never reached the wire"
        )
        assert session.approval.provide(["m1"]) is True
        await asyncio.wait_for(consumer, timeout=10)
        return chunks

    chunks = asyncio.run(scenario())
    joined = "".join(chunks)
    # The card went out, the approval went in, and the write actually ran.
    assert '"tool":"remember"' in joined
    assert "event: done" in joined
    assert agent._SESSIONS == {}
    with SessionLocal() as db:
        stored = db.query(Memory).filter(Memory.user_id == USER).count()
    assert stored == 1, "the approved write must have reached the memory store"


def test_ask_user_is_announced_live_and_the_stream_keeps_pinging(monkeypatch):
    _hermetic(monkeypatch)
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {
                        "name": "ask_user",
                        "args": {"question": "Which repo?", "options": ["a", "b"]},
                        "id": "q1",
                    },
                )
            ),
            ScriptedTurn(text="Noted."),
        ]
    )

    async def scenario():
        session = agent._register(agent._TurnSession(turn_id="t-ask", user_id=USER))
        chunks: list[str] = []

        async def consume():
            async for chunk in agent._stream_agent(
                turn=_turn("t-ask", "Which repo should I use?"),
                model=model,
                session=session,
                model_id=MODEL,
            ):
                chunks.append(chunk)

        consumer = asyncio.ensure_future(consume())
        for _ in range(250):
            await asyncio.sleep(0.02)
            if any("event: ask_user" in chunk for chunk in chunks):
                break
        # The question must arrive while the tool is still waiting -- that is
        # the whole point -- and the open wait must keep the stream alive.
        assert any("event: ask_user" in chunk for chunk in chunks), (
            "the question was not announced while the turn waited"
        )
        for _ in range(150):
            await asyncio.sleep(0.02)
            if any(": ping" in chunk for chunk in chunks):
                break
        assert any(": ping" in chunk for chunk in chunks), (
            "an open gate must keep pinging the client"
        )
        assert session.ask.provide({"text": "a"}) is True
        await asyncio.wait_for(consumer, timeout=10)
        return chunks

    chunks = asyncio.run(scenario())
    joined = "".join(chunks)
    assert "Which repo?" in joined
    assert "event: done" in joined
    assert agent._SESSIONS == {}


def test_a_decision_for_a_foreign_or_unknown_turn_is_a_404():
    session = agent._register(agent._TurnSession(turn_id="t-owned", user_id=USER))

    with pytest.raises(HTTPException) as unknown:
        asyncio.run(
            agent.decide(
                agent.DecisionRequest(user_id=USER, turn_id="t-none", call_ids=["x"])
            )
        )
    assert unknown.value.status_code == 404

    with pytest.raises(HTTPException) as foreign:
        asyncio.run(
            agent.answer(
                agent.AnswerRequest(
                    user_id="someone-else", turn_id="t-owned", answer="no"
                )
            )
        )
    assert foreign.value.status_code == 404

    # An empty list is a decline, not a validation error: the gate reads it
    # as "nothing on this card is approved" and the loop denies them all.
    recorded = asyncio.run(
        agent.decide(
            agent.DecisionRequest(user_id=USER, turn_id="t-owned", call_ids=[])
        )
    )
    assert recorded["status"] == "recorded"

    agent._SESSIONS.pop(session.turn_id, None)


def test_closing_the_stream_drops_the_session(monkeypatch):
    """Stop is a disconnect: the generator's finally must clean up after it."""
    _hermetic(monkeypatch)
    model = MockLLM([ScriptedTurn(text="Hello.")])

    async def scenario():
        session = agent._register(agent._TurnSession(turn_id="t-close", user_id=USER))
        stream = agent._stream_agent(
            turn=_turn("t-close", "hi"),
            model=model,
            session=session,
            model_id=MODEL,
        )
        assert (await stream.__anext__())  # conversation identity
        await stream.aclose()
        assert "t-close" not in agent._SESSIONS

    asyncio.run(scenario())


def test_regenerate_reruns_without_storing_the_question_again(monkeypatch):
    _hermetic(monkeypatch)
    monkeypatch.setattr(
        agent,
        "make_chat_model",
        lambda *_a, **_k: MockLLM([ScriptedTurn(text="A fresh answer.")]),
    )

    with TestClient(app) as client:
        first = client.post(
            "/api/agent/chat",
            json={
                "user_id": USER,
                "conversation_id": CONVERSATION,
                "model": MODEL,
                "message": "What is 42?",
            },
        )
        assert first.status_code == 200
        # Simulate the failure retry exists for: the answer never persisted.
        with SessionLocal() as db:
            db.query(Message).filter(
                Message.conversation_id == CONVERSATION,
                Message.role == "assistant",
            ).delete()
            db.commit()

        retry = client.post(
            "/api/agent/chat",
            json={
                "user_id": USER,
                "conversation_id": CONVERSATION,
                "model": MODEL,
                "message": "What is 42?",
                "regenerate": True,
            },
        )
        assert retry.status_code == 200

        stored = client.get(
            f"/api/conversations/{CONVERSATION}", params={"user_id": USER}
        ).json()["messages"]

    assert [row["role"] for row in stored] == ["user", "assistant"]
    assert stored[1]["content"] == "A fresh answer."


def test_badges_come_from_cached_probe_rows_not_the_network():
    with TestClient(app) as client:
        data = client.get("/api/agent/badges").json()

    assert data[MODEL]["native_tools"] is True
    assert data[MODEL]["badge"] in {"Strong", "Basic", "Prompted-only"}
    # Nothing was probed to answer this: the seeded row is the only row.
    with SessionLocal() as db:
        probed = (
            db.query(ModelCapabilities)
            .filter(ModelCapabilities.model_id == MODEL)
            .count()
        )
    assert probed == 1
