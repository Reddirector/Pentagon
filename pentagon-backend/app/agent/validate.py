"""Validation and repair between the model's raw calls and the executor.

The model's arguments are untrusted input shaped like JSON: they arrive
sometimes as strings with code fences or trailing commas, sometimes with
numbers where ints are required, sometimes missing declared defaults. This
layer fixes what can be fixed *safely*, and turns everything else into a
corrective tool message that quotes the exact errors and the schema -- the
model learns from that and retries, at most twice per tool per turn, after
which it is told to answer without the tool.

Nothing here changes the meaning of arguments for write/destructive tools:
coercion is limited to string-to-number and string-to-bool, which JSONSchema
semantics already imply.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, FormatChecker
from jsonschema.exceptions import ValidationError

from app.agent.injection import exfiltration_risk
from app.agent.schemas import ToolResult, ToolSpec


class RepairTracker:
    """Per-turn memory of how often each tool's arguments failed validation.

    After ``limit`` failures for one tool, further calls of that tool are not
    executed at all: the model gets a refusal telling it to answer without
    the tool or ask the user, which stops an argument-repair infinite loop.
    """

    def __init__(self, limit: int = 2) -> None:
        self.limit = limit
        self._failures: dict[str, int] = {}

    def register_failure(self, tool: str) -> int:
        self._failures[tool] = self._failures.get(tool, 0) + 1
        return self._failures[tool]

    def exhausted(self, tool: str) -> bool:
        return self._failures.get(tool, 0) >= self.limit


@dataclass(frozen=True)
class ValidatedCall:
    """The outcome of validating one raw model call."""

    executable: bool
    tool: str
    args: dict[str, Any]
    tool_call_id: str
    # Set only when not executable: the envelope the model receives instead.
    refusal: ToolResult | None = None


_FENCE = re.compile(r"^```[a-zA-Z0-9_-]*\s*|\s*```$", re.MULTILINE)


def parse_arguments(tool: str, raw: Any) -> tuple[dict[str, Any] | None, ToolResult | None]:
    """The model's raw arguments as a dict, or a failure explaining why not.

    Strings go through safe fixes -- code fences stripped, trailing commas
    removed, smart quotes normalised -- before ``json.loads``. A list or
    scalar is not silently wrapped: the model must re-send an object.
    """
    if raw is None:
        return {}, None
    if isinstance(raw, dict):
        return raw, None
    if isinstance(raw, str):
        text = raw.strip()
        text = _FENCE.sub("", text).strip()
        text = text.replace("\u201c", '"').replace("\u201d", '"')
        text = text.replace("\u2018", "'").replace("\u2019", "'")
        text = re.sub(r",\s*([}\]])", r"\1", text)
        if not text:
            return {}, None
        try:
            parsed = json.loads(text)
        except ValueError:
            return None, ToolResult.failure(
                "INVALID_ARGS",
                f"The arguments for {tool} were not valid JSON: {text[:200]}",
                hint="Re-send the call with arguments as a JSON object.",
            )
        if isinstance(parsed, dict):
            return parsed, None
        return None, ToolResult.failure(
            "INVALID_ARGS",
            f"The arguments for {tool} parsed as {type(parsed).__name__}, not an object.",
            hint='Arguments must be a JSON object, e.g. {"query": "..."}.',
        )
    return None, ToolResult.failure(
        "INVALID_ARGS",
        f"The arguments for {tool} were {type(raw).__name__}, not a JSON object.",
        hint="Arguments must be a JSON object.",
    )


def coerce_and_fill(spec: ToolSpec, args: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Safe coercions and declared defaults, then schema validation.

    Returns the (possibly adjusted) args and a list of human-readable
    validation errors; empty errors means the call may execute.
    """
    adjusted = dict(args)
    properties = spec.parameters.get("properties", {}) or {}
    for key, value in list(adjusted.items()):
        schema = properties.get(key)
        if not isinstance(schema, dict):
            continue
        expected = schema.get("type")
        if expected == "integer" and isinstance(value, str):
            try:
                adjusted[key] = int(value.strip())
            except ValueError:
                pass
        elif expected == "number" and isinstance(value, str):
            try:
                adjusted[key] = float(value.strip())
            except ValueError:
                pass
        elif expected == "boolean" and isinstance(value, str):
            lowered = value.strip().lower()
            if lowered in ("true", "yes"):
                adjusted[key] = True
            elif lowered in ("false", "no"):
                adjusted[key] = False
    for key, schema in properties.items():
        if key in adjusted or not isinstance(schema, dict):
            continue
        if "default" in schema:
            adjusted[key] = schema["default"]

    errors: list[str] = []
    validator = Draft202012Validator(spec.parameters, format_checker=FormatChecker())
    for error in validator.iter_errors(adjusted):
        errors.append(_format_error(error))
    return adjusted, errors


def _format_error(error: ValidationError) -> str:
    where = ".".join(str(part) for part in error.absolute_path) or "(root)"
    return f"{where}: {error.message}"


def _compact_schema(spec: ToolSpec) -> str:
    return json.dumps(spec.parameters, ensure_ascii=False, separators=(",", ":"))


def validate_call(
    call: dict[str, Any],
    lookup,
    tracker: RepairTracker,
    valid_names: list[str] | None = None,
) -> ValidatedCall:
    """Validate one raw call end to end; ``lookup(name) -> ToolSpec | None``.

    Unknown tools are refused with the valid names; unparseable or
    schema-invalid arguments are refused with the exact errors plus the
    schema; a tool whose repairs are exhausted is refused outright.
    """
    name = str(call.get("name") or "")
    call_id = str(call.get("id") or "")
    spec = lookup(name)
    if spec is None:
        shown = ", ".join(sorted(valid_names)) if valid_names else "(none available)"
        return ValidatedCall(
            executable=False,
            tool=name,
            args={},
            tool_call_id=call_id,
            refusal=ToolResult.failure(
                "NOT_FOUND",
                f"Unknown tool {name!r}. Valid tools: {shown}",
                hint="Pick one of the valid tools and resend the call with its schema's arguments.",
            ),
        )
    if tracker.exhausted(name):
        return ValidatedCall(
            executable=False,
            tool=name,
            args={},
            tool_call_id=call_id,
            refusal=ToolResult.failure(
                "DENIED",
                f"The arguments for {name} failed validation twice, so this tool"
                " will not be called again this turn.",
                hint="Answer the user without this tool, or ask them for the missing values.",
            ),
        )

    args, failure = parse_arguments(name, call.get("args"))
    if failure is not None:
        tracker.register_failure(name)
        return ValidatedCall(
            executable=False, tool=name, args={}, tool_call_id=call_id, refusal=failure
        )

    assert args is not None
    args, errors = coerce_and_fill(spec, args)
    if errors:
        tracker.register_failure(name)
        return ValidatedCall(
            executable=False,
            tool=name,
            args=args,
            tool_call_id=call_id,
            refusal=ToolResult.failure(
                "INVALID_ARGS",
                "The arguments did not match the schema: " + " | ".join(errors[:4]),
                hint=f"The schema for {name} is: {_compact_schema(spec)}",
            ),
        )

    # T7 exfiltration guard: credential-shaped material must never leave in
    # tool arguments -- checked here, before the approval card and before the
    # trace, so the secret cannot leak via either. The refusal names the rule
    # that matched, never the matched value. This is not a schema failure, so
    # it does not count against the model's repair budget: removing the
    # secret and resending is a valid next move.
    risk = exfiltration_risk(args)
    if risk is not None:
        return ValidatedCall(
            executable=False,
            tool=name,
            args=args,
            tool_call_id=call_id,
            refusal=ToolResult.failure(
                "DENIED",
                f"The arguments for {name} were not sent: they {risk}.",
                hint=(
                    "Tools never receive credentials. Take any key, token or "
                    "password out of the arguments and try again."
                ),
            ),
        )

    return ValidatedCall(executable=True, tool=name, args=args, tool_call_id=call_id)
