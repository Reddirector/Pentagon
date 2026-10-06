"""The prompted tool protocol, for models that failed the capability probe.

The descriptors go into the system prompt in a compact form and the model is
told to answer with one or more ``<tool_call>{"name": ..., "arguments": ...}``
blocks and nothing else. Parsing is deliberately strict -- a strict parser
plus the repair loop beats a lenient parser that guesses -- but the safe
cosmetic fixes (code fences, trailing commas, smart quotes) from the
validation layer apply here too.

Everything parsed here becomes exactly the call dicts the native path
produces, so the rest of the loop cannot tell the difference.
"""

from __future__ import annotations

import json
import re
from typing import Any

from app.agent.schemas import ToolSpec
from app.agent.validate import parse_arguments

_CALL_SPAN = re.compile(r"<tool_call>(.*?)</tool_call>", re.DOTALL)
_FENCE = re.compile(r"```[a-zA-Z0-9_-]*\s*|\s*```")
_TRAILING_COMMA = re.compile(r",\s*([}\]])")


def _extract_object(text: str) -> str | None:
    """The first balanced JSON object in ``text`` (string-aware brace counting)."""
    start = text.find("{")
    if start < 0:
        return None
    depth = 0
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def prompt_for_tools(specs: list[ToolSpec]) -> str:
    """The instruction block that goes into the system prompt."""
    lines = [
        "# Tools",
        "",
        "You can use tools. To call one, reply with a block exactly like this",
        "(and nothing else on that turn except one short sentence of plan):",
        "",
        '<tool_call>{"name": "<tool_name>", "arguments": { ... }}</tool_call>',
        "",
        "You may include several tool_call blocks in one reply to call several",
        "tools. After each of your tool calls you will receive the result, and",
        "then you continue. Never invent a tool result.",
        "",
    ]
    for spec in specs:
        params = json.dumps(spec.parameters, ensure_ascii=False, separators=(",", ":"))
        lines.append(f"- {spec.name}: {spec.description}")
        lines.append(f"  Arguments schema: {params}")
    return "\n".join(lines)


def parse_tool_calls(reply_text: str) -> tuple[list[dict[str, Any]], list[str]]:
    """Every well-formed call in the reply, plus one note per malformed block.

    Returns ``(calls, problems)``. A block whose JSON will not parse, or whose
    arguments are not an object, is reported in ``problems`` with its exact
    defect so the validation layer can turn it into a corrective message;
    well-formed blocks in the same reply still execute.
    """
    calls: list[dict[str, Any]] = []
    problems: list[str] = []
    for match in _CALL_SPAN.finditer(reply_text):
        inner = _FENCE.sub("", match.group(1)).strip()
        raw = _extract_object(inner)
        if raw is None:
            problems.append(f"a tool_call block contained no JSON object: {inner[:200]}")
            continue
        raw = _TRAILING_COMMA.sub(r"\1", raw)
        try:
            block = json.loads(raw)
        except ValueError:
            problems.append(f"a tool_call block was not valid JSON: {raw[:200]}")
            continue
        if not isinstance(block, dict) or not isinstance(block.get("name"), str):
            problems.append(f"a tool_call block had no tool name: {raw[:200]}")
            continue
        name = block["name"]
        args, failure = parse_arguments(name, block.get("arguments"))
        if failure is not None:
            problems.append(f"{name}: {failure.error.message}" if failure.error else f"{name}: invalid arguments")
            continue
        calls.append({"name": name, "args": args or {}, "id": f"prompted_{len(calls)}"})
    return calls, problems
