"""The Docker sandbox: the only place agent-written Python is ever executed.

Rules this module exists to keep (upgrade prompt T8):

- **Docker only, never the host.** ``run_python`` shells out to a single
  ``docker run`` of the image built from ``sandbox/Dockerfile.python``. No
  code path feeds model-written source to the local interpreter; when Docker
  is missing or its daemon is down, :func:`sandbox_available` says so and the
  tool layer fails honestly instead of falling back to the host.
- **Hardened by default.** :func:`build_run_argv` is the single place the
  container flags are decided: no network, read-only rootfs, all capabilities
  dropped, no privilege escalation, non-root user, pid/memory/cpu caps, and a
  tmpfs for /tmp. Tests assert the flags stay present.
- **Timeouts really stop the container.** Killing the ``docker run`` client
  does not stop the container, so every timeout path issues ``docker kill``
  by container name (and user cancellation does the same, fire-and-forget,
  because a stopped turn must not leave a runaway sleep loop behind).
"""

from __future__ import annotations

import asyncio
import shutil
import subprocess
import time
import uuid
from dataclasses import dataclass
from pathlib import Path

# Built from sandbox/Dockerfile.python (pinned python:3.12-slim, uid 10001).
IMAGE_TAG = "pentagon-sandbox:py312"
DOCKERFILE_DIR = Path(__file__).resolve().parents[2] / "sandbox"
DOCKERFILE = DOCKERFILE_DIR / "Dockerfile.python"

# The model-facing defaults. The outer executor timeout for python_exec sits
# above MAX_TIMEOUT_SECONDS so the inner kill always wins the race.
DEFAULT_TIMEOUT_SECONDS = 15.0
MAX_TIMEOUT_SECONDS = 60.0
MAX_CODE_CHARS = 100_000
MAX_OUTPUT_CHARS = 8_000

_AVAILABILITY_TTL_SECONDS = 30.0
_KILL_TIMEOUT_SECONDS = 10.0
_REAP_TIMEOUT_SECONDS = 15.0

_available_checked_at: float | None = None
_available: bool | None = None
_image_ready = False


class SandboxUnavailable(RuntimeError):
    """Docker (or the sandbox image) is missing; execution is disabled."""


@dataclass
class SandboxOutcome:
    """What one sandboxed run produced, before any envelope mapping."""

    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool
    duration_ms: float
    stdout_truncated: bool
    stderr_truncated: bool
    docker_error: bool


def reset_state() -> None:
    """Forget cached availability and image state (tests use this)."""
    global _available, _available_checked_at, _image_ready
    _available = None
    _available_checked_at = None
    _image_ready = False


def sandbox_available() -> bool:
    """True when the docker CLI exists and its daemon answers, cached 30s.

    The cache keeps ``build_registry`` from paying a ``docker info`` round
    trip on every call; ``reset_state`` exists for tests that need to flip
    the answer.
    """
    global _available, _available_checked_at
    now = time.monotonic()
    if (
        _available is not None
        and _available_checked_at is not None
        and now - _available_checked_at < _AVAILABILITY_TTL_SECONDS
    ):
        return _available
    _available = shutil.which("docker") is not None and _daemon_reachable()
    _available_checked_at = now
    return _available


def _daemon_reachable() -> bool:
    try:
        proc = subprocess.run(
            ["docker", "info", "--format", "{{.ServerVersion}}"],
            capture_output=True,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return proc.returncode == 0


def build_run_argv(code: str, *, name: str, image: str = IMAGE_TAG) -> list[str]:
    """The full ``docker run`` command line, hardening flags included.

    Kept pure so tests can assert the isolation flags without a daemon: no
    network, read-only rootfs, dropped capabilities, no privilege escalation,
    non-root uid, pids/memory/cpu ceilings, tmpfs /tmp, and the program is
    passed to ``python -I -c`` (isolated mode, stdin and environment unused,
    so nothing from the host environment reaches the program).
    """
    return [
        "docker",
        "run",
        "--rm",
        "--name",
        name,
        "--network",
        "none",
        "--read-only",
        "--cap-drop",
        "ALL",
        "--security-opt",
        "no-new-privileges",
        "--pids-limit",
        "64",
        "--memory",
        "256m",
        "--memory-swap",
        "256m",
        "--cpus",
        "1.0",
        "--tmpfs",
        "/tmp:rw,size=32m,mode=1777",
        "--user",
        "10001:10001",
        image,
        "python",
        "-I",
        "-c",
        code,
    ]


def ensure_image() -> None:
    """Build sandbox/Dockerfile.python if its image is not already present.

    Synchronous and meant to be called via ``asyncio.to_thread``; the build
    is a one-time cost and a no-op afterwards while the image exists.
    """
    global _image_ready
    if _image_ready:
        return
    if shutil.which("docker") is None:
        raise SandboxUnavailable("the docker CLI is not installed")
    if not DOCKERFILE.is_file():
        raise SandboxUnavailable(f"sandbox Dockerfile missing at {DOCKERFILE}")
    try:
        inspect = subprocess.run(
            ["docker", "image", "inspect", IMAGE_TAG],
            capture_output=True,
            timeout=15,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxUnavailable(f"docker is not reachable: {exc}") from exc
    if inspect.returncode == 0:
        _image_ready = True
        return
    try:
        build = subprocess.run(
            [
                "docker",
                "build",
                "-t",
                IMAGE_TAG,
                "-f",
                str(DOCKERFILE),
                str(DOCKERFILE_DIR),
            ],
            capture_output=True,
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise SandboxUnavailable(f"could not build the sandbox image: {exc}") from exc
    if build.returncode != 0:
        tail = build.stderr.decode(errors="replace")[-500:]
        raise SandboxUnavailable(f"the sandbox image build failed: {tail}")
    _image_ready = True


async def run_python(code: str, *, timeout_s: float) -> SandboxOutcome:
    """Run ``code`` in a fresh hardened container and collect its output.

    Raises :class:`SandboxUnavailable` when the container cannot be started;
    returns a :class:`SandboxOutcome` (including ``docker_error`` outcomes)
    when it ran. ``timeout_s`` kills the *container* by name -- killing the
    CLI alone would leave it running.
    """
    if not sandbox_available():
        raise SandboxUnavailable("docker is not available on this server")
    await asyncio.to_thread(ensure_image)
    name = f"pentagon-sbx-{uuid.uuid4().hex[:12]}"
    argv = build_run_argv(code, name=name)
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise SandboxUnavailable(f"could not start docker: {exc}") from exc

    stdout_task = asyncio.ensure_future(proc.stdout.read())
    stderr_task = asyncio.ensure_future(proc.stderr.read())
    readers = asyncio.ensure_future(asyncio.gather(stdout_task, stderr_task))
    started = time.monotonic()
    timed_out = False
    try:
        try:
            # Shielded so a timeout never cancels the readers underneath us.
            await asyncio.wait_for(asyncio.shield(readers), timeout_s)
        except asyncio.TimeoutError:
            timed_out = True
            try:
                await _kill_container(name)
            except asyncio.CancelledError:
                # Stopped while killing: schedule another kill and bail out.
                _kill_later(name)
                readers.cancel()
                try:
                    proc.terminate()
                except ProcessLookupError:
                    pass
                raise
            try:
                await asyncio.wait_for(asyncio.shield(readers), _REAP_TIMEOUT_SECONDS)
            except asyncio.TimeoutError:
                pass
        except asyncio.CancelledError:
            # User Stop or an executor deadline: the container dies with the
            # turn, fire-and-forget because we are being cancelled right now.
            _kill_later(name)
            readers.cancel()
            try:
                proc.terminate()
            except ProcessLookupError:
                pass
            raise
        try:
            await asyncio.wait_for(asyncio.shield(proc.wait()), _REAP_TIMEOUT_SECONDS)
        except asyncio.TimeoutError:
            pass
    finally:
        if not readers.done():
            readers.cancel()

    stdout_raw = _first_bytes(stdout_task)
    stderr_raw = _first_bytes(stderr_task)
    stdout, stdout_truncated = _clip(stdout_raw)
    stderr, stderr_truncated = _clip(stderr_raw)
    exit_code = proc.returncode
    # docker run exits 125 for its own failures; a program that exits 125
    # would have to also look like a docker error in stderr to be mistaken.
    docker_error = exit_code == 125 and (
        stderr.startswith("docker:") or "Error response from daemon" in stderr
    )
    return SandboxOutcome(
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        timed_out=timed_out,
        duration_ms=round((time.monotonic() - started) * 1000, 1),
        stdout_truncated=stdout_truncated,
        stderr_truncated=stderr_truncated,
        docker_error=docker_error,
    )


async def _kill_container(name: str) -> None:
    """``docker kill`` by name -- the only reliable way to stop a container."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "docker",
            "kill",
            name,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
        )
        await asyncio.wait_for(proc.wait(), _KILL_TIMEOUT_SECONDS)
    except (OSError, asyncio.TimeoutError):
        pass


def _kill_later(name: str) -> None:
    """Schedule the kill without awaiting it (we may be mid-cancellation)."""
    try:
        task = asyncio.create_task(_kill_container(name))
    except RuntimeError:  # event loop already closing
        return

    def _consume(done: "asyncio.Task[None]") -> None:
        if not done.cancelled():
            done.exception()

    task.add_done_callback(_consume)


def _first_bytes(task: "asyncio.Task[bytes]") -> bytes:
    if not task.done() or task.cancelled():
        return b""
    try:
        value = task.result()
    except (asyncio.CancelledError, asyncio.IncompleteReadError, OSError):
        return b""
    return value if isinstance(value, bytes) else b""


def _clip(raw: bytes) -> tuple[str, bool]:
    """Decode capped output: the sandbox must not blow out the context."""
    truncated = len(raw) > MAX_OUTPUT_CHARS
    return raw[:MAX_OUTPUT_CHARS].decode(errors="replace"), truncated
