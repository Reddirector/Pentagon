"""Planning and asking: the plan stays honest, the pause actually resumes."""

import asyncio

import pytest

from app.agent.bootstrap import build_registry
from app.agent.loop import TurnRequest, run_turn
from app.agent.planner import PlanError, normalize_plan, plan_summary
from app.agent.schemas import AskUserGate, Budget, ToolContext
from app.db.models import Conversation, User
from app.db.session import SessionLocal
from app.evals.mock_llm import MockLLM, ScriptedTurn
from app.tools import ask_user, update_plan


@pytest.fixture(autouse=True)
def _loop_rows():
    """The user and conversation rows the trace flush's foreign keys want."""
    with SessionLocal() as db:
        if db.get(User, "loop-test") is None:
            db.add(User(id="loop-test"))
        if db.get(Conversation, "conv-test") is None:
            db.add(Conversation(id="conv-test", user_id="loop-test", title="loop"))
        db.commit()
    yield


def _ctx(**overrides) -> ToolContext:
    fields = {
        "user_id": "u",
        "conversation_id": "c",
        "turn_id": "t",
        "permission_level": 2,
    }
    fields.update(overrides)
    return ToolContext(**fields)


# --- the plan invariants ------------------------------------------------------

def test_normalize_plan_accepts_a_valid_list():
    steps = normalize_plan(
        [
            {"text": "Search", "status": "done"},
            {"text": "Compare", "status": "in_progress"},
            {"text": "Write up", "status": "pending"},
        ]
    )
    assert [step["status"] for step in steps] == ["done", "in_progress", "pending"]


def test_normalize_plan_demotes_extra_in_progress_steps():
    steps = normalize_plan(
        [
            {"text": "A", "status": "in_progress"},
            {"text": "B", "status": "in_progress"},
            {"text": "C", "status": "in_progress"},
        ]
    )
    assert [step["status"] for step in steps] == ["in_progress", "pending", "pending"]


def test_normalize_plan_rejects_too_many_steps():
    with pytest.raises(PlanError):
        normalize_plan([{"text": f"step {i}"} for i in range(8)])


def test_normalize_plan_rejects_bad_statuses_and_empty_text():
    with pytest.raises(PlanError):
        normalize_plan([{"text": "A", "status": "finished"}])
    with pytest.raises(PlanError):
        normalize_plan([{"text": "   "}])
    with pytest.raises(PlanError):
        normalize_plan([])


def test_plan_summary_counts_and_names_the_current_step():
    summary = plan_summary(
        [
            {"text": "A", "status": "done"},
            {"text": "B", "status": "in_progress"},
        ]
    )
    assert summary == "1/2 done -- now: B"


# --- update_plan tool -----------------------------------------------------------

def test_update_plan_publishes_to_shared_state():
    shared: dict = {}
    result = asyncio.run(update_plan.run({"steps": [{"text": "Do it"}]}, _ctx(shared=shared)))
    assert result.ok is True
    assert shared["plan"][0]["text"] == "Do it"


def test_update_plan_rejects_structurally_broken_plans():
    result = asyncio.run(update_plan.run({"steps": []}, _ctx()))
    assert result.ok is False
    assert result.error.code == "INVALID_ARGS"
    assert "7" in result.error.hint


# --- ask_user -------------------------------------------------------------------

def test_ask_user_pauses_and_resumes_with_the_answer():
    gate = AskUserGate()

    async def scenario():
        ctx = _ctx(pause_gate=gate)
        task = asyncio.ensure_future(ask_user.run({"question": "Which repo?"}, ctx))
        await asyncio.sleep(0.05)
        assert gate.provide({"text": "backend"})
        return await task

    result = asyncio.run(scenario())
    assert result.ok is True
    assert result.data["answer"]["text"] == "backend"


def test_ask_user_times_out_with_a_honest_envelope(monkeypatch):
    import app.tools.ask_user as module

    # Nobody answers; shrink the wait so the test is quick.
    monkeypatch.setattr(module, "_ASK_TIMEOUT_SECONDS", 0.05)
    gate = AskUserGate()

    result = asyncio.run(ask_user.run({"question": "Which repo?"}, _ctx(pause_gate=gate)))
    assert result.ok is False
    assert result.error.code == "UPSTREAM"
    assert "assumption" in result.error.hint.lower()


def test_ask_user_without_a_gate_says_so_instead_of_hanging():
    result = asyncio.run(ask_user.run({"question": "Which repo?"}, _ctx()))
    assert result.ok is False
    assert result.error.code == "UPSTREAM"
    assert "no interactive user" in result.error.message


def test_ask_user_validates_question_and_options():
    long_question = "x" * 501
    bad = asyncio.run(ask_user.run({"question": long_question}, _ctx()))
    assert bad.ok is False and bad.error.code == "INVALID_ARGS"

    bad_options = asyncio.run(
        ask_user.run({"question": "ok?", "options": ["a", 3]}, _ctx())
    )
    assert bad_options.ok is False and bad_options.error.code == "INVALID_ARGS"


# --- the loop streams plan and ask events ---------------------------------------

def _request(**overrides) -> TurnRequest:
    fields = {
        "user_id": "loop-test",
        "conversation_id": "conv-test",
        "turn_id": "t-plan",
        "permission_level": 2,
        "user_message": "plan something",
        "system_prompt": "You are Pentagon.",
    }
    fields.update(overrides)
    return TurnRequest(**fields)


def test_loop_emits_plan_events():
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {
                        "name": "update_plan",
                        "args": {
                            "steps": [
                                {"text": "Find sources", "status": "in_progress"},
                                {"text": "Write the summary", "status": "pending"},
                            ]
                        },
                        "id": "p1",
                    },
                )
            ),
            ScriptedTurn(text="Plan is set, proceeding."),
        ]
    )

    async def collect():
        return [
            event
            async for event in run_turn(registry, model, _request(), budget=Budget(max_llm_calls=4))
        ]

    events = asyncio.run(collect())
    plan_events = [e for e in events if e.name == "plan"]
    assert len(plan_events) == 1
    assert plan_events[0].payload["steps"][0]["text"] == "Find sources"
    assert plan_events[0].payload["steps"][0]["status"] == "in_progress"
