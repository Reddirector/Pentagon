"""Run the eval task suite against the mock LLM (default) or ``--live``.

Usage, from ``pentagon-backend``:

    ../pentagon/bin/python -m app.evals.run_evals
    ../pentagon/bin/python -m app.evals.run_evals --filter time

Tasks live in ``app/evals/tasks/*.yaml``. A task passes when every assertion
in it holds against the agent's behavior on its scripted fixtures. The mock
suite is deterministic -- CI fails on any red. ``--live`` spends real NVIDIA
requests and is only ever run by a human.

The injection suite (``app/evals/injection_suite.yaml``, T7) always runs
alongside the tasks: it exercises the spotlight, the detector, the
exfiltration guard and the permission ladder against known attacks and known
benign text. Any failing injection case is a failed run, regardless of how
the tasks did.
"""

from __future__ import annotations

import argparse
import asyncio
import shutil
import sys
from pathlib import Path
from typing import Any
from unittest.mock import patch

import yaml

from app.agent.injection import detect_injection, exfiltration_risk, spotlight
from app.services.permissions import requires_tool_approval

TASKS_DIR = Path(__file__).parent / "tasks"
INJECTION_SUITE = Path(__file__).parent / "injection_suite.yaml"


def load_tasks(directory: Path = TASKS_DIR) -> list[dict[str, Any]]:
    """Every task in ``*.yaml``; a file may hold one task or a list of them."""
    tasks: list[dict[str, Any]] = []
    for path in sorted(directory.glob("*.yaml")):
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
        if isinstance(data, list):
            tasks.extend(item for item in data if isinstance(item, dict))
        elif isinstance(data, dict):
            tasks.append(data)
    return tasks


# Evaluation writes are namespaced to one synthetic user and cleaned up
# afterwards, so a run leaves nothing behind: trace rows need a user and a
# conversation to point at, memories and capability seeds are removed, and
# the artifact folder for the turn goes too.
EVAL_USER = "eval-user"
EVAL_CONVERSATION = "eval-conv"
EVAL_MODEL_ID = "eval-model"

# The default search fixture: deterministic, offline, on a host citations can
# be checked against, carrying one fact worth citing.
DEFAULT_SEARCH_RESULTS: list[dict[str, Any]] = [
    {
        "title": "Annual report 2025",
        "url": "https://example.com/report",
        "content": "Revenue grew 12 percent in 2025, driven by the platform segment.",
    },
]


def _ensure_eval_rows() -> None:
    """The trace recorder's foreign keys need their rows to exist."""
    from app.db.models import Conversation, User
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        if db.get(User, EVAL_USER) is None:
            db.add(User(id=EVAL_USER))
        if db.get(Conversation, EVAL_CONVERSATION) is None:
            db.add(
                Conversation(
                    id=EVAL_CONVERSATION, user_id=EVAL_USER, title="eval suite"
                )
            )
        db.commit()


def _clear_eval_state() -> None:
    """Memories, traces and capability seeds never outlive their task."""
    from app.db.models import Memory, ModelCapabilities, ToolTrace
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.query(Memory).filter(Memory.user_id == EVAL_USER).delete()
        db.query(ToolTrace).filter(ToolTrace.user_id == EVAL_USER).delete()
        db.query(ModelCapabilities).filter(
            ModelCapabilities.model_id == EVAL_MODEL_ID
        ).delete()
        db.commit()


def _seed_capabilities(task: dict[str, Any]) -> None:
    """Record the probe row a routed task needs, before the loop asks.

    Every task that routes by capability seeds its row explicitly: a missing
    row would make the loop probe the real endpoint, and evaluation must
    never spend a request to learn what the fixture already knows.
    """
    caps = task.get("capabilities")
    if not caps:
        return
    from app.db.models import ModelCapabilities
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        db.add(
            ModelCapabilities(
                model_id=EVAL_MODEL_ID,
                native_tools=bool(caps.get("native_tools", True)),
                parallel_tools=bool(caps.get("parallel_tools", True)),
            )
        )
        db.commit()


def _script_for(task: dict[str, Any]) -> list[Any]:
    from app.evals.mock_llm import ScriptedTurn

    turns = []
    for step in task.get("script") or []:
        turns.append(
            ScriptedTurn(
                text=str(step.get("text", "")),
                tool_calls=tuple(dict(call) for call in (step.get("tool_calls") or [])),
                # YAML cannot carry an exception; the message becomes one.
                error=(RuntimeError(str(step["error"])) if step.get("error") else None),
            )
        )
    return turns


async def _collect_turn(registry, model, request, budget, gate):
    from app.agent.loop import run_turn

    return [
        event
        async for event in run_turn(
            registry, model, request, budget=budget, approval_gate=gate
        )
    ]


def _final_text(events: list[Any]) -> str:
    return "".join(
        str(event.payload.get("content", ""))
        for event in events
        if event.name == "token"
    )


def _check_expect(
    task: dict[str, Any], events: list[Any], model: Any, budget: Any
) -> str | None:
    """Every assertion the task declares; ``None`` means the task passed."""
    expect = dict(task.get("expect") or {})
    names = [event.name for event in events]

    # A turn never ends silently: no done event is always a failure.
    if "done" not in names:
        return "the turn ended without a done event"

    # Unscripted error events fail unless the task explicitly budgets for
    # them, and the message is the reason -- the failure explains itself.
    errors = [event for event in events if event.name == "error"]
    allowed_errors = int((expect.get("events") or {}).get("error", 0))
    if len(errors) > allowed_errors:
        message = errors[0].payload.get("message", "")
        return f"unexpected error event: {message}"

    if "tools" in expect:
        got = [
            event.payload.get("tool")
            for event in events
            if event.name == "tool_result"
        ]
        if got != list(expect["tools"]):
            return f"tools executed {got}, expected {list(expect['tools'])}"

    for tool, status in (expect.get("tool_status") or {}).items():
        got = [
            event.payload.get("status")
            for event in events
            if event.name == "tool_result" and event.payload.get("tool") == tool
        ]
        if not got:
            return f"tool {tool!r} never produced a result"
        if any(value != status for value in got):
            return f"tool {tool!r} had statuses {got}, expected {status}"

    for name, count in (expect.get("events") or {}).items():
        got = sum(1 for value in names if value == name)
        if got != int(count):
            return f"event {name!r} fired {got} times, expected {count}"

    text = _final_text(events)
    for needle in expect.get("mentions") or []:
        if str(needle) not in text:
            shown = text[:160] if text else "<no tokens streamed>"
            return f"the answer never says {needle!r} (got: {shown!r})"
    for needle in expect.get("forbids") or []:
        if str(needle) in text:
            return f"the answer says {needle!r} but must not"
    if "answer_is" in expect and text != str(expect["answer_is"]):
        return f"final answer {text!r} != {expect['answer_is']!r}"

    if "verification" in expect:
        want = expect["verification"]
        verdict = next(
            (
                event.payload.get("verification")
                for event in events
                if event.name == "done"
            ),
            None,
        )
        if want is False:
            if verdict is not None:
                return f"verification ran ({verdict}) but the task expects none"
        elif not isinstance(verdict, dict):
            return "the done event carries no verification verdict"
        else:
            for key, value in dict(want).items():
                if verdict.get(key) != value:
                    return (
                        f"verification[{key}]={verdict.get(key)!r}, "
                        f"expected {value!r}"
                    )

    if "native_bound" in expect:
        bound = bool(model.bound_tools)
        if bound != bool(expect["native_bound"]):
            return (
                "native tool schemas were offered to the model"
                if bound
                else "no native tool schemas were ever offered to the model"
            )

    for cap_key, field in (
        ("llm_calls_max", "llm_calls"),
        ("tool_calls_max", "tool_calls"),
    ):
        if cap_key in expect and getattr(budget, field) > int(expect[cap_key]):
            return f"{field}={getattr(budget, field)} exceeds {expect[cap_key]}"

    statuses = [
        str(event.payload.get("message", ""))
        for event in events
        if event.name == "status"
    ]
    for needle in expect.get("status_contains") or []:
        if not any(str(needle) in message for message in statuses):
            return f"no status event mentions {needle!r}"

    summaries = [
        str(event.payload.get("summary", ""))
        for event in events
        if event.name == "tool_result"
    ]
    for needle in expect.get("result_contains") or []:
        if not any(str(needle) in summary for summary in summaries):
            return f"no tool result contains {needle!r}"

    if "plan" in expect:
        plans = [
            event.payload.get("steps") for event in events if event.name == "plan"
        ]
        if expect["plan"] not in plans:
            return f"plan events {plans!r} do not include {expect['plan']!r}"

    if "approval_calls" in expect:
        got = [
            call.get("tool")
            for event in events
            if event.name == "approval_required"
            for call in event.payload.get("calls", [])
        ]
        if got != list(expect["approval_calls"]):
            return (
                f"the approval card covered {got}, "
                f"expected {list(expect['approval_calls'])}"
            )

    if "tokens_min" in expect:
        count = sum(1 for value in names if value == "token")
        if count < int(expect["tokens_min"]):
            return (
                f"only {count} token events, expected at least "
                f"{expect['tokens_min']}"
            )

    return None


def _run_mock(task: dict[str, Any], task_id: str) -> dict[str, Any]:
    """Drive the real agent loop with the scripted model. Offline by design."""
    from app.agent.bootstrap import build_registry
    from app.agent.executor import clear_cache
    from app.agent.loop import TurnRequest
    from app.agent.schemas import ApprovalGate, Budget
    from app.config import settings as app_settings
    from app.evals.mock_llm import MockLLM

    model = MockLLM(_script_for(task))
    _ensure_eval_rows()
    _clear_eval_state()
    _seed_capabilities(task)

    request = TurnRequest(
        user_id=EVAL_USER,
        conversation_id=EVAL_CONVERSATION,
        turn_id=f"eval-{task_id}",
        permission_level=int(task.get("level", 2)),
        user_message=str(task.get("prompt", "")),
        model_id=EVAL_MODEL_ID if task.get("capabilities") else task.get("model_id"),
    )
    spec = dict(task.get("budget") or {})
    budget = Budget(
        max_llm_calls=int(spec.get("max_llm_calls", 8)),
        max_tool_calls=int(spec.get("max_tool_calls", 16)),
        max_seconds=float(spec.get("max_seconds", 120.0)),
    )
    gate = None
    if task.get("approve"):
        gate = ApprovalGate()
        gate.provide([str(call_id) for call_id in task["approve"]])

    search_results = task.get("search_results", DEFAULT_SEARCH_RESULTS)
    search_error = bool(task.get("search_error"))

    async def _fake_search(query: str) -> list[dict[str, Any]]:
        del query
        if search_error:
            raise RuntimeError("eval fixture: the search provider is offline")
        return [dict(row) for row in search_results]

    registry = build_registry()
    clear_cache()
    try:
        with patch("app.tools.web_search.search_web", _fake_search):
            events = asyncio.run(_collect_turn(registry, model, request, budget, gate))
    except Exception as exc:
        want = dict(task.get("expect") or {}).get("raises")
        if want and str(want) in repr(exc):
            return {"id": task_id, "passed": True, "reason": ""}
        return {"id": task_id, "passed": False, "reason": f"the turn raised {exc!r}"}
    finally:
        _clear_eval_state()
        directory = Path(getattr(app_settings, "artifact_directory", "./artifacts"))
        shutil.rmtree(directory / f"eval-{task_id}", ignore_errors=True)

    raises = dict(task.get("expect") or {}).get("raises")
    if raises:
        return {
            "id": task_id,
            "passed": False,
            "reason": f"the task expects the turn to raise {raises!r}, but it completed",
        }

    reason = _check_expect(task, events, model, budget)
    if reason:
        return {"id": task_id, "passed": False, "reason": reason}
    return {"id": task_id, "passed": True, "reason": ""}


def _run_live(task: dict[str, Any], task_id: str) -> dict[str, Any]:
    """Run one marked task against the real model. Human-run only: it spends.

    Live assertions are looser than the mock's on purpose: a real model is
    not a script, so the task checks what the user would notice -- the turn
    finished without errors, the expected tools ran, the facts are present.
    """
    from app.agent.bootstrap import build_registry
    from app.agent.executor import clear_cache
    from app.agent.loop import TurnRequest
    from app.agent.schemas import Budget
    from app.config import settings as app_settings
    from app.db.session import SessionLocal
    from app.security.keys import resolve_api_key
    from app.services.nvidia_client import make_chat_model

    _ensure_eval_rows()
    _clear_eval_state()
    with SessionLocal() as db:
        key = resolve_api_key(db, EVAL_USER)
    if not key:
        return {
            "id": task_id,
            "passed": False,
            "reason": "no NVIDIA key is configured; --live needs one",
        }

    model_id = app_settings.default_chat_model or "meta/llama-3.3-70b-instruct"
    model = make_chat_model(key, model_id)
    request = TurnRequest(
        user_id=EVAL_USER,
        conversation_id=EVAL_CONVERSATION,
        turn_id=f"eval-{task_id}",
        permission_level=int(task.get("level", 3)),
        user_message=str(task.get("prompt", "")),
    )
    budget = Budget(max_llm_calls=8, max_tool_calls=8, max_seconds=90.0)
    registry = build_registry()
    clear_cache()
    try:
        events = asyncio.run(_collect_turn(registry, model, request, budget, None))
    except Exception as exc:
        return {"id": task_id, "passed": False, "reason": f"the live turn raised {exc!r}"}
    finally:
        _clear_eval_state()

    if "done" not in [event.name for event in events]:
        return {
            "id": task_id,
            "passed": False,
            "reason": "the live turn ended without a done event",
        }
    errors = [event for event in events if event.name == "error"]
    if errors:
        return {
            "id": task_id,
            "passed": False,
            "reason": f"error event: {errors[0].payload.get('message', '')}",
        }
    text = _final_text(events)
    if not text.strip():
        return {"id": task_id, "passed": False, "reason": "the live answer was empty"}

    expect = dict(task.get("live_expect") or {})
    ran = sorted(
        {
            str(event.payload.get("tool"))
            for event in events
            if event.name == "tool_result"
        }
    )
    for tool in expect.get("tools") or []:
        if tool not in ran:
            return {
                "id": task_id,
                "passed": False,
                "reason": f"expected tool {tool!r} to run; tools were {ran}",
            }
    for needle in expect.get("mentions") or []:
        if str(needle) not in text:
            return {
                "id": task_id,
                "passed": False,
                "reason": f"the live answer never says {needle!r}",
            }
    return {"id": task_id, "passed": True, "reason": ""}


def run_task(task: dict[str, Any], *, live: bool) -> dict[str, Any]:
    """Execute one task and return ``{id, passed, reason}``.

    Mock mode (the default, the CI gate) drives the real agent loop with the
    deterministic scripted model: no network, no key, every assertion about
    observable events. ``--live`` runs only tasks marked ``live: true``
    against the real model -- looser assertions, real NVIDIA quota, so it is
    a human's command and never CI's.
    """
    task_id = str(task.get("id", "<unnamed>"))
    if live and not task.get("live"):
        return {"id": task_id, "passed": False, "reason": "not marked live: true"}
    try:
        return _run_live(task, task_id) if live else _run_mock(task, task_id)
    except Exception as exc:  # a runner crash fails the task; it never skips
        return {"id": task_id, "passed": False, "reason": f"the eval runner crashed: {exc!r}"}


def load_injection_suite(path: Path = INJECTION_SUITE) -> list[dict[str, Any]]:
    """Every case in the injection suite; missing file means empty (not green)."""
    if not path.exists():
        return []
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [item for item in data if isinstance(item, dict)]
    return [data] if isinstance(data, dict) else []


def run_injection_case(case: dict[str, Any]) -> dict[str, Any]:
    """Evaluate one injection-suite case against the real defenses.

    Returns ``{id, passed, reason}``. Every kind asserts observable behavior
    of the shipped code -- no mocks, no network.
    """
    case_id = str(case.get("id", "<unnamed>"))
    kind = str(case.get("kind", ""))
    expect = str(case.get("expect", ""))

    if kind == "detect":
        flags = detect_injection(str(case.get("text", "")))
        if expect == "flagged":
            passed = bool(flags)
            reason = "" if passed else "the detector let a known attack through"
        elif expect == "clean":
            passed = not flags
            reason = "" if passed else f"false positive: matched {flags}"
        else:
            passed = False
            reason = f"unknown expect value {expect!r}"
        return {"id": case_id, "passed": passed, "reason": reason}

    if kind == "exfiltration":
        risk = exfiltration_risk(case.get("args"))
        if expect == "denied":
            passed = risk is not None
            reason = "" if passed else "credential-shaped arguments were allowed through"
        elif expect == "allowed":
            passed = risk is None
            reason = "" if passed else f"false positive: denied because they {risk}"
        else:
            passed = False
            reason = f"unknown expect value {expect!r}"
        return {"id": case_id, "passed": passed, "reason": reason}

    if kind == "spotlight":
        wrapped = spotlight(str(case.get("tool", "web_search")), str(case.get("text", "")))
        has_open = "<<<UNTRUSTED" in wrapped
        has_close = "<<<END UNTRUSTED>>>" in wrapped
        # The wrapper's own pair must survive; embedded forgeries must not
        # add or remove markers beyond that pair.
        open_count = wrapped.count("<<<UNTRUSTED")
        close_count = wrapped.count("<<<END UNTRUSTED>>>")
        passed = expect == "wrapped" and has_open and has_close and open_count == 1 and close_count == 1
        reason = "" if passed else (
            f"markers wrong: open={open_count} close={close_count}"
        )
        return {"id": case_id, "passed": passed, "reason": reason}

    if kind == "permission":
        tier = str(case.get("tier", "read"))
        level = int(case.get("level", 2))
        needs = requires_tool_approval(tier, level)
        if expect == "approval_required":
            passed = needs
            reason = "" if passed else f"{tier}@L{level} ran without approval despite injected text"
        elif expect == "auto":
            passed = not needs
            reason = "" if passed else f"{tier}@L{level} demanded approval it should not need"
        else:
            passed = False
            reason = f"unknown expect value {expect!r}"
        return {"id": case_id, "passed": passed, "reason": reason}

    return {"id": case_id, "passed": False, "reason": f"unknown kind {kind!r}"}


def run_injection_suite(path: Path = INJECTION_SUITE) -> list[dict[str, Any]]:
    return [run_injection_case(case) for case in load_injection_suite(path)]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run the Pentagon eval suite")
    parser.add_argument("--filter", default="", help="only run tasks whose id contains this")
    parser.add_argument(
        "--live",
        action="store_true",
        help="run against the real model (spends NVIDIA quota; human-run only)",
    )
    args = parser.parse_args(argv)

    tasks = [task for task in load_tasks() if args.filter in str(task.get("id", ""))]

    if args.live:
        # Only tasks explicitly marked live: true may ever spend a request.
        live_tasks = [task for task in tasks if task.get("live")]
        if not live_tasks:
            print("no task in this selection is marked live: true")
            return 1
        live_results = [run_task(task, live=True) for task in live_tasks]
        for result in live_results:
            mark = "PASS" if result["passed"] else "FAIL"
            print(f"{mark}  {result['id']} (live)")
            if not result["passed"] and result.get("reason"):
                print(f"      {result['reason']}")
        live_failures = [r for r in live_results if not r["passed"]]
        print(
            f"\n{len(live_results) - len(live_failures)}/{len(live_results)} "
            "live tasks passed"
        )
        return 0 if not live_failures else 1

    results = [run_task(task, live=False) for task in tasks]
    injection = run_injection_suite()

    for result in results:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark}  {result['id']}")
        if not result["passed"] and result.get("reason"):
            print(f"      {result['reason']}")
    for result in injection:
        mark = "PASS" if result["passed"] else "FAIL"
        print(f"{mark}  {result['id']}")
        if not result["passed"] and result.get("reason"):
            print(f"      {result['reason']}")

    all_results = [*results, *injection]
    failures = [r for r in all_results if not r["passed"]]
    print(f"\n{len(all_results) - len(failures)}/{len(all_results)} passed")
    if not tasks:
        print("warning: no eval tasks found - that is a failed gate")
        failures = [*failures, {"id": "<eval-tasks>"}]
    if not injection:
        print("warning: injection suite missing or empty - that is a failed gate")
        failures = [*failures, {"id": "<injection-suite>"}]
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
