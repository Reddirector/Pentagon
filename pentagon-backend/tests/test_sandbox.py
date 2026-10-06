"""T8: model-written code runs only in Docker, behind the hardening flags.

Unit tests pin the rules that must hold even without a daemon (the argv
carries every isolation flag, missing Docker disables the tools instead of
falling back to the host, artifacts never escape their folder). The ``live``
tests actually start containers and verify network-less, read-only,
kill-on-timeout behaviour for real; they skip when Docker is absent.
"""

import asyncio
import subprocess
import time

import pytest

from app.agent.bootstrap import build_registry
from app.agent.loop import TurnRequest, run_turn
from app.agent.schemas import Budget, ToolContext
from app.config import settings
from app.db.models import Conversation, User
from app.db.session import SessionLocal
from app.evals.mock_llm import MockLLM, ScriptedTurn
from app.services import sandbox_runner
from app.tools import create_artifact, python_exec

_DOCKER = sandbox_runner.sandbox_available()
live = pytest.mark.skipif(not _DOCKER, reason="the docker sandbox is unavailable")


@pytest.fixture(autouse=True)
def _sandbox_state():
    """Each test sees a cold availability/image cache."""
    sandbox_runner.reset_state()
    yield
    sandbox_runner.reset_state()


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


# --- the isolation flags are not optional ---------------------------------


def test_run_argv_carries_every_isolation_flag():
    argv = sandbox_runner.build_run_argv("print(1)", name="pentagon-sbx-unit")
    line = " ".join(argv)
    for flag in (
        "--network none",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges",
        "--pids-limit 64",
        "--memory 256m",
        "--memory-swap 256m",
        "--cpus 1.0",
        "--tmpfs /tmp:rw,size=32m,mode=1777",
        "--user 10001:10001",
        "--rm",
    ):
        assert flag in line, f"missing {flag}"
    # Nothing that could widen the blast radius.
    assert "--privileged" not in argv
    assert not any(a in ("--volume", "-v", "--mount", "--env", "-e") for a in argv)
    # The program goes in isolated, on stdin-free -c, as the last argument.
    assert argv[1] == "run"
    assert argv[-4:] == ["python", "-I", "-c", "print(1)"]


def test_dockerfile_is_pinned_and_non_root():
    text = sandbox_runner.DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM python:3.12-slim" in text
    assert ":latest" not in text
    assert "USER sandbox" in text
    assert "--uid 10001" in text


# --- availability gates registration, never execution on the host ---------


def test_availability_is_false_when_the_cli_is_missing(monkeypatch):
    monkeypatch.setattr(sandbox_runner.shutil, "which", lambda *_a, **_k: None)
    assert sandbox_runner.sandbox_available() is False


def test_registry_hides_sandbox_tools_without_docker(monkeypatch):
    monkeypatch.setattr(sandbox_runner, "sandbox_available", lambda: False)
    assert not {"python_exec", "create_artifact"} & set(build_registry().names())
    monkeypatch.setattr(sandbox_runner, "sandbox_available", lambda: True)
    names = build_registry().names()
    assert "python_exec" in names
    assert "create_artifact" in names


def test_python_exec_denied_without_docker_and_never_spawns(monkeypatch):
    monkeypatch.setattr(sandbox_runner, "sandbox_available", lambda: False)

    def _no_spawn(*_a, **_k):
        raise AssertionError("a process was spawned without docker")

    monkeypatch.setattr(sandbox_runner, "run_python", _no_spawn)
    result = asyncio.run(python_exec.run({"code": "print(1)"}, _ctx()))
    assert result.ok is False
    assert result.error.code == "DENIED"
    assert "never falls back to the host" in result.error.hint


# --- argument validation never reaches a process ----------------------------


def test_python_exec_validates_its_arguments(monkeypatch):
    monkeypatch.setattr(sandbox_runner, "sandbox_available", lambda: True)
    for bad in ({}, {"code": ""}, {"code": "   "}, {"code": "print(1)\x00"}):
        result = asyncio.run(python_exec.run(bad, _ctx()))
        assert result.ok is False, bad
        assert result.error.code == "INVALID_ARGS"
    too_big = "x" * (sandbox_runner.MAX_CODE_CHARS + 1)
    result = asyncio.run(python_exec.run({"code": too_big}, _ctx()))
    assert result.ok is False and result.error.code == "INVALID_ARGS"
    for bad_timeout in (0, 999, "fast", True):
        result = asyncio.run(
            python_exec.run({"code": "print(1)", "timeout_s": bad_timeout}, _ctx())
        )
        assert result.ok is False, bad_timeout
        assert result.error.code == "INVALID_ARGS"


def test_python_exec_maps_a_clean_run(monkeypatch):
    monkeypatch.setattr(sandbox_runner, "sandbox_available", lambda: True)
    captured: dict = {}

    async def _ok(code, *, timeout_s):
        captured["code"], captured["timeout_s"] = code, timeout_s
        return sandbox_runner.SandboxOutcome(
            0, "4\n", "", False, 12.0, False, False, False
        )

    monkeypatch.setattr(sandbox_runner, "run_python", _ok)
    result = asyncio.run(
        python_exec.run({"code": "print(2+2)", "timeout_s": 7}, _ctx())
    )
    assert result.ok is True
    assert result.data["exit_code"] == 0
    assert result.data["stdout"] == "4\n"
    assert result.data["timed_out"] is False
    assert result.data["sandbox"] == "docker:none,readonly,nonroot"
    assert captured == {"code": "print(2+2)", "timeout_s": 7.0}


def test_python_exec_reports_a_container_that_never_started(monkeypatch):
    monkeypatch.setattr(sandbox_runner, "sandbox_available", lambda: True)

    async def _broken(code, *, timeout_s):
        return sandbox_runner.SandboxOutcome(
            125, "", "docker: Cannot connect to the daemon", False, 5.0, False, False, True
        )

    monkeypatch.setattr(sandbox_runner, "run_python", _broken)
    result = asyncio.run(python_exec.run({"code": "print(1)"}, _ctx()))
    assert result.ok is False
    assert result.error.code == "UPSTREAM"
    assert "daemon" in result.error.hint


def test_python_exec_keeps_a_timeout_visible(monkeypatch):
    monkeypatch.setattr(sandbox_runner, "sandbox_available", lambda: True)

    async def _slow(code, *, timeout_s):
        return sandbox_runner.SandboxOutcome(
            137, "", "", True, 60_000.0, False, False, False
        )

    monkeypatch.setattr(sandbox_runner, "run_python", _slow)
    result = asyncio.run(python_exec.run({"code": "import time; time.sleep(99)"}, _ctx()))
    assert result.ok is True
    assert result.data["timed_out"] is True
    assert result.data["exit_code"] == 137


# --- create_artifact ---------------------------------------------------------


def test_create_artifact_writes_the_file_and_publishes_it(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_directory", str(tmp_path))
    shared: dict = {}
    result = asyncio.run(
        create_artifact.run(
            {
                "name": "quarterly.md",
                "content": "# Sum",
                "media_type": "text/markdown",
            },
            _ctx(shared=shared),
        )
    )
    assert result.ok is True
    stored = tmp_path / "t" / "quarterly.md"
    assert stored.read_text(encoding="utf-8") == "# Sum"
    assert result.data["id"] == "t/quarterly.md"
    assert result.data["bytes"] == 5
    assert result.data["media_type"] == "text/markdown"
    assert shared["artifact"]["path"] == str(stored)


def test_create_artifact_refuses_paths_oversize_and_bad_types(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_directory", str(tmp_path))
    for name in ("../evil.txt", "sub/report.md", "/etc/passwd", ".hidden", "", "x" * 81):
        result = asyncio.run(create_artifact.run({"name": name, "content": "x"}, _ctx()))
        assert result.ok is False, name
        assert result.error.code == "INVALID_ARGS"
    for content in ("", "   "):
        result = asyncio.run(
            create_artifact.run({"name": "ok.txt", "content": content}, _ctx())
        )
        assert result.ok is False
        assert result.error.code == "INVALID_ARGS"
    result = asyncio.run(
        create_artifact.run(
            {"name": "ok.txt", "content": "x" * 1_000_001}, _ctx()
        )
    )
    assert result.ok is False and result.error.code == "INVALID_ARGS"
    result = asyncio.run(
        create_artifact.run(
            {"name": "ok.txt", "content": "x", "media_type": "weird"}, _ctx()
        )
    )
    assert result.ok is False and result.error.code == "INVALID_ARGS"


def test_create_artifact_turn_folder_can_never_escape(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "artifact_directory", str(tmp_path))
    result = asyncio.run(
        create_artifact.run({"name": "a.txt", "content": "x"}, _ctx(turn_id=".."))
    )
    assert result.ok is True
    assert (tmp_path / "turn" / "a.txt").exists()
    result = asyncio.run(
        create_artifact.run({"name": "b.txt", "content": "x"}, _ctx(turn_id="../escape"))
    )
    assert result.ok is True
    assert (tmp_path / ".._escape" / "b.txt").exists()
    assert not (tmp_path.parent / "escape").exists()


# --- the loop tells the client an artifact exists ------------------------------


def test_loop_emits_the_artifact_event(monkeypatch, tmp_path):
    monkeypatch.setattr(sandbox_runner, "sandbox_available", lambda: True)
    monkeypatch.setattr(settings, "artifact_directory", str(tmp_path))
    registry = build_registry()
    model = MockLLM(
        [
            ScriptedTurn(
                tool_calls=(
                    {
                        "name": "create_artifact",
                        "args": {"name": "out.txt", "content": "hello"},
                        "id": "a1",
                    },
                )
            ),
            ScriptedTurn(text="Saved."),
        ]
    )
    request = TurnRequest(
        user_id="loop-test",
        conversation_id="conv-test",
        turn_id="t-artifact",
        # Trusted: a write would otherwise (correctly) raise an approval card
        # and this test is about the event, not the gate.
        permission_level=3,
        user_message="save the result as a file",
        system_prompt="You are Pentagon.",
    )

    async def collect():
        return [
            event
            async for event in run_turn(
                registry, model, request, budget=Budget(max_llm_calls=4)
            )
        ]

    events = asyncio.run(collect())
    artifacts = [event for event in events if event.name == "artifact"]
    assert len(artifacts) == 1
    assert artifacts[0].payload["name"] == "out.txt"
    assert artifacts[0].payload["bytes"] == 5
    assert artifacts[0].payload["turn_id"] == "t-artifact"


# --- live containers ------------------------------------------------------------


def _sandbox_containers() -> set[str]:
    proc = subprocess.run(
        ["docker", "ps", "-aq", "--filter", "name=pentagon-sbx-"],
        capture_output=True,
        text=True,
        timeout=10,
    )
    return {line for line in proc.stdout.split() if line}


@live
def test_live_python_exec_runs_code_in_the_container():
    result = asyncio.run(python_exec.run({"code": "print(2+2)"}, _ctx()))
    assert result.ok is True
    assert result.data["stdout"].strip() == "4"
    assert result.data["exit_code"] == 0
    assert result.data["timed_out"] is False


@live
def test_live_container_cannot_reach_the_network():
    code = (
        "import socket\n"
        "s = socket.socket()\n"
        "s.settimeout(3)\n"
        "try:\n"
        "    s.connect(('1.1.1.1', 80))\n"
        "    print('OPEN')\n"
        "except Exception:\n"
        "    print('blocked')\n"
    )
    result = asyncio.run(python_exec.run({"code": code}, _ctx()))
    assert result.ok is True
    assert "blocked" in result.data["stdout"]


@live
def test_live_rootfs_is_read_only():
    outcome = asyncio.run(
        sandbox_runner.run_python("open('/etc/x', 'w')", timeout_s=15)
    )
    assert outcome.exit_code != 0
    assert "Read-only file system" in outcome.stderr


@live
def test_live_timeout_kills_the_container_and_leaves_nothing_behind():
    before = _sandbox_containers()
    outcome = asyncio.run(
        sandbox_runner.run_python("import time; time.sleep(60)", timeout_s=2)
    )
    assert outcome.timed_out is True
    assert outcome.duration_ms < 15_000
    # docker kill by name: the container must actually disappear.
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline and (_sandbox_containers() - before):
        time.sleep(0.2)
    assert not (_sandbox_containers() - before)


@live
def test_live_output_is_clipped_for_the_context():
    outcome = asyncio.run(
        sandbox_runner.run_python("print('x' * 100000)", timeout_s=15)
    )
    assert outcome.stdout_truncated is True
    assert len(outcome.stdout) == sandbox_runner.MAX_OUTPUT_CHARS


@live
def test_live_program_exit_code_is_reported():
    outcome = asyncio.run(sandbox_runner.run_python("import sys; sys.exit(3)", timeout_s=15))
    assert outcome.exit_code == 3
    assert outcome.timed_out is False
