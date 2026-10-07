"""skill_router in the chat graph — the §6 acceptance checklist, end to end.

These drive the real graph (and, for persistence, the real chat route) with
a fake model that records the prompt it was handed, because two halves of
the contract meet at that prompt: what was injected *for this turn*, and
what must never appear in what was *stored*. One assertion proves the skill
reached the model, the other proves it did not reach the thread.
"""

from __future__ import annotations

import asyncio
import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage
from sqlalchemy import select

from app.config import settings
from app.db.models import ApiKey, Message, User
from app.db.session import SessionLocal
from app.main import app
from app.security.crypto import encrypt_api_key
from app.services import chat_graph
from app.skills import loader as loader_module

_PROMPTS: list[list] = []


class PromptCapturingModel:
    """Stands in for the model; records exactly what would have been sent."""

    async def ainvoke(self, messages, config=None):
        _PROMPTS.append(list(messages))
        return AIMessage(content="fake answer")


@pytest.fixture
def root(tmp_path, monkeypatch):
    (tmp_path / "public").mkdir()
    (tmp_path / "user").mkdir()
    monkeypatch.setattr(loader_module, "DEFAULT_SKILLS_DIR", tmp_path)
    return tmp_path


@pytest.fixture(autouse=True)
def fake_model(monkeypatch):
    _PROMPTS.clear()
    monkeypatch.setattr(
        chat_graph, "make_chat_model", lambda *_a, **_k: PromptCapturingModel()
    )
    monkeypatch.setattr(chat_graph, "has_documents", lambda _conversation_id: False)
    yield
    _PROMPTS.clear()


def write_skill(root, skill_id: str, *, triggers: list[str], body: str, requires: list[str] | None = None):
    directory = root / "user" / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    lines = [
        "---",
        f"name: {skill_id}",
        f"description: A crafted skill about {'/'.join(triggers)} topics for matcher tests.",
        f"triggers: [{', '.join(triggers)}]",
        "risk_category: read",
    ]
    if requires:
        lines.append(f"requires_tools: [{', '.join(requires)}]")
    lines += ["---", "", body, ""]
    (directory / "SKILL.md").write_text("\n".join(lines), encoding="utf-8")


def run_turn(message: str, *, user_id: str = "skill-user") -> dict:
    state = chat_graph.initial_chat_state(
        user_id=user_id,
        conversation_id=f"conv-{uuid4()}",
        message=message,
        history=[],
        use_web_search=None,
    )
    graph = chat_graph.build_chat_graph(
        "unused-test-key", "test-model", user_id=user_id, use_web_search=None
    )
    return asyncio.run(graph.ainvoke(state))


def last_prompt() -> str:
    assert _PROMPTS, "the model was never invoked"
    return "\n".join(
        message.content
        for message in _PROMPTS[-1]
        if isinstance(getattr(message, "content", None), str)
    )


def test_zero_matches_injects_nothing_and_logs_an_empty_list(root, caplog) -> None:
    write_skill(root, "alpha", triggers=["apples"], body="ALPHA BODY MARKER")
    with caplog.at_level(logging.INFO, logger="app.skills.router"):
        result = run_turn("What is the capital of France?")

    assert result["skills_fired"] == []
    assert result["skill_instructions"] == ""
    assert result["execution_trace"]["skill_router"]["skill_count"] == 0
    assert "### Skill:" not in result["augmented_prompt"]
    assert "ALPHA BODY MARKER" not in last_prompt()
    messages = [record.getMessage() for record in caplog.records]
    assert any("skills fired: []" in message for message in messages), messages


def test_one_match_loads_only_that_body(root) -> None:
    write_skill(root, "alpha", triggers=["apples"], body="ALPHA BODY MARKER")
    write_skill(root, "beta", triggers=["bananas"], body="BETA BODY MARKER")

    result = run_turn("Tell me everything about apples")

    assert result["skills_fired"] == ["alpha"]
    prompt = last_prompt()
    assert "ALPHA BODY MARKER" in prompt, "the matched skill's body must reach the model"
    assert "BETA BODY MARKER" not in prompt, "the neighbour's body must not be loaded"


def test_multiple_matches_load_up_to_the_cap(root) -> None:
    for n in range(4):
        write_skill(root, f"pack-{n}", triggers=[f"unicorntopic{n}"], body=f"PACK {n} MARKER")

    result = run_turn(
        "unicorntopic0 unicorntopic1 unicorntopic2 unicorntopic3 are all I care about"
    )

    # All four are equally relevant; the tie breaks on id and the cap keeps
    # the fourth out.
    assert result["skills_fired"] == ["pack-0", "pack-1", "pack-2"]
    prompt = last_prompt()
    for skill_id in ("pack-0", "pack-1", "pack-2"):
        assert f"### Skill: {skill_id}" in prompt
    assert "PACK 3 MARKER" not in prompt, "the fourth skill must be capped out"


def test_missing_capability_note_is_prepended_but_body_still_loads(root) -> None:
    write_skill(
        root,
        "ghost",
        triggers=["ghosttopic"],
        requires=["definitely_not_a_tool"],
        body="GHOST BODY MARKER",
    )

    result = run_turn("please handle ghosttopic for me")

    assert result["skills_fired"] == ["ghost"], "a missing tool must not block loading"
    prompt = last_prompt()
    assert "GHOST BODY MARKER" in prompt
    note_at = prompt.find("not available")
    body_at = prompt.find("GHOST BODY MARKER")
    assert note_at != -1
    assert "definitely_not_a_tool" in prompt
    assert 0 < note_at < body_at, "the capability note must be visibly prepended"


def test_disabled_skill_stops_firing_for_the_next_turn(root, monkeypatch) -> None:
    """Acceptance §6.7: off, verified by re-sending what previously fired."""
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    write_skill(root, "alpha", triggers=["penguinparty"], body="ALPHA BODY MARKER")
    user_id = f"skill-toggle-{uuid4()}"
    # The route decrypts the stored key during the toggle's own request, so
    # the secret has to stay swapped for the whole test, not just the insert.
    monkeypatch.setattr(
        settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode())
    )
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=encrypt_api_key("nvapi-test-key"),
                masked_key="nvapi-...key",
            )
        )
        db.commit()

    before = run_turn("run the penguinparty please", user_id=user_id)
    assert before["skills_fired"] == ["alpha"], "sanity: it fires while enabled"
    assert "ALPHA BODY MARKER" in last_prompt()

    with TestClient(app) as client:
        toggled = client.patch(
            "/api/skills/alpha",
            json={"user_id": user_id, "enabled": False},
        )
        assert toggled.status_code == 200, toggled.text

    after = run_turn("run the penguinparty please", user_id=user_id)
    assert after["skills_fired"] == [], "a disabled skill must be excluded entirely"
    assert "ALPHA BODY MARKER" not in last_prompt()


def test_new_skill_file_fires_on_a_later_turn_without_restart(root) -> None:
    """Acceptance §6.1, through the graph rather than the index directly."""
    first = run_turn("what about the qubitcalibur question")
    assert first["skills_fired"] == []

    write_skill(root, "qubit", triggers=["qubitcalibur"], body="QUBIT BODY MARKER")
    second = run_turn("what about the qubitcalibur question")
    assert second["skills_fired"] == ["qubit"]
    assert "QUBIT BODY MARKER" in last_prompt()


def test_skill_body_never_reaches_stored_thread_history(root, monkeypatch) -> None:
    """Acceptance §6.5: injected this turn, absent from stored state forever."""
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    write_skill(root, "alpha", triggers=["penguinparty"], body="ALPHA PERSIST MARKER")
    user_id = f"skill-persist-{uuid4()}"
    monkeypatch.setattr(
        settings, "key_encryption_secret", SecretStr(Fernet.generate_key().decode())
    )
    with SessionLocal() as db:
        db.add(User(id=user_id))
        db.add(
            ApiKey(
                user_id=user_id,
                encrypted_key=encrypt_api_key("nvapi-test-key"),
                masked_key="nvapi-...key",
            )
        )
        db.commit()

    with TestClient(app) as client:
        conversation_id = client.post(
            "/api/conversations", json={"user_id": user_id, "title": "Skills"}
        ).json()["id"]
        response = client.post(
            "/api/chat",
            json={
                "user_id": user_id,
                "conversation_id": conversation_id,
                "model": "test/model",
                "message": "run the penguinparty now",
            },
        )
    assert response.status_code == 200, response.text

    # The model received the skill...
    assert "ALPHA PERSIST MARKER" in last_prompt()
    # ...and the stored thread did not.
    with SessionLocal() as db:
        stored = list(
            db.scalars(
                select(Message).where(Message.conversation_id == conversation_id)
            )
        )
    assert stored, "the turn should have stored both messages"
    for message in stored:
        assert "ALPHA PERSIST MARKER" not in message.content, (
            f"skill body leaked into stored {message.role} message"
        )
        assert "### Skill:" not in message.content
