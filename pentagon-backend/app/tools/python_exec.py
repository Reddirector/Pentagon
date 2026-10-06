"""python_exec: run model-written Python, but only inside the Docker sandbox.

This is the one tool that executes code, so it carries T8's hardest rule: if
the sandbox cannot be created, the call fails with an honest DENIED instead
of quietly running the program on the host. The tier is ``write`` -- the T7
permission ladder puts write behind an approval card at Restricted and
Balanced, so arbitrary code never runs unattended except at Trusted.
"""

from __future__ import annotations

from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.services import sandbox_runner

TOOL_SPEC = ToolSpec(
    name="python_exec",
    description=(
        "Execute a short Python program inside an isolated Docker sandbox and"
        " get stdout, stderr and the exit code. Use for any computation where"
        " code beats mental arithmetic: numeric work beyond the calculator,"
        " parsing or transforming data, generating tables or reports,"
        " checking logic over a list. The sandbox has no network access and"
        " only the standard library; it cannot fetch URLs or install"
        " packages. One self-contained program per call -- print the result;"
        " files written inside the sandbox are discarded with it (use"
        " create_artifact to hand a result file to the user)."
    ),
    parameters={
        "type": "object",
        "properties": {
            "code": {
                "type": "string",
                "description": (
                    "Python source, run with `python -I -c`. Standard library"
                    " only, no network. Print whatever the caller needs."
                ),
            },
            "timeout_s": {
                "type": "number",
                "description": (
                    "Seconds to allow before the sandbox is killed"
                    f" (1-{sandbox_runner.MAX_TIMEOUT_SECONDS:.0f}); default"
                    f" {sandbox_runner.DEFAULT_TIMEOUT_SECONDS:.0f}."
                ),
            },
        },
        "required": ["code"],
    },
    # Arbitrary code is a state-changing capability: the approval ladder
    # gates it at Restricted and Balanced, and only Trusted runs it cold.
    tier="write",
    timeout_s=int(sandbox_runner.MAX_TIMEOUT_SECONDS) + 15,
    cacheable=False,
    # Programs can be nondeterministic; never replay a cached run.
    idempotent=False,
    parallel_safe=True,
    tags=(
        "python",
        "code",
        "exec",
        "execute",
        "script",
        "compute",
        "program",
        "sandbox",
        "interpret",
    ),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    if not sandbox_runner.sandbox_available():
        return ToolResult.failure(
            "DENIED",
            "Python execution is disabled: this server has no working Docker"
            " sandbox.",
            hint=(
                "Code only ever runs inside the container built from"
                " sandbox/Dockerfile.python -- it never falls back to the"
                " host interpreter. Solve this without executing code."
            ),
        )
    code = args.get("code")
    if not isinstance(code, str) or not code.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "code must be a non-empty string of Python source.",
            hint="Pass the program as the 'code' argument, then print results.",
        )
    if len(code) > sandbox_runner.MAX_CODE_CHARS:
        return ToolResult.failure(
            "INVALID_ARGS",
            f"code is {len(code)} chars; the limit is"
            f" {sandbox_runner.MAX_CODE_CHARS}.",
            hint="Split the work into smaller programs across calls.",
        )
    if "\x00" in code:
        return ToolResult.failure(
            "INVALID_ARGS",
            "code contains a NUL byte, which cannot be passed to the"
            " interpreter.",
            hint="Remove the \\0 characters and run again.",
        )
    timeout_s = sandbox_runner.DEFAULT_TIMEOUT_SECONDS
    if "timeout_s" in args and args["timeout_s"] is not None:
        raw = args["timeout_s"]
        if (
            isinstance(raw, bool)
            or not isinstance(raw, (int, float))
            or not 1 <= raw <= sandbox_runner.MAX_TIMEOUT_SECONDS
        ):
            return ToolResult.failure(
                "INVALID_ARGS",
                f"timeout_s must be a number between 1 and"
                f" {sandbox_runner.MAX_TIMEOUT_SECONDS:.0f}.",
                hint="Drop it for the default or pick a value in range.",
            )
        timeout_s = float(raw)

    try:
        outcome = await sandbox_runner.run_python(code, timeout_s=timeout_s)
    except sandbox_runner.SandboxUnavailable as exc:
        return ToolResult.failure(
            "DENIED",
            f"The sandbox could not be started: {exc}.",
            hint=(
                "Code never runs on the host itself; retry once Docker is"
                " back, or answer without executing anything."
            ),
        )
    if outcome.docker_error:
        return ToolResult.failure(
            "UPSTREAM",
            "The sandbox container failed to start.",
            hint=(outcome.stderr or outcome.stdout)[:400] or None,
        )
    return ToolResult.success(
        {
            "exit_code": outcome.exit_code,
            "timed_out": outcome.timed_out,
            "stdout": outcome.stdout,
            "stderr": outcome.stderr,
            "output_truncated": outcome.stdout_truncated
            or outcome.stderr_truncated,
            "duration_ms": outcome.duration_ms,
            "sandbox": "docker:none,readonly,nonroot",
        }
    )
