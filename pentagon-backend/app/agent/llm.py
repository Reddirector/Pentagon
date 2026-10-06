"""The model-facing side of the loop: bind tools, call, assemble tool calls.

NVIDIA's endpoint is OpenAI-compatible: tools ride on the request as
``{"type": "function", ...}`` descriptors and come back as assistant
``tool_calls``. In a stream the arguments arrive as deltas keyed by ``index``
-- id and name once, then argument fragments to concatenate -- so assembly is
only correct after the stream has ended. This module owns that surface through
langchain, against any model object with the ``bind_tools``/``ainvoke``/
``astream`` shape: the real ChatOpenAI in production, the mock in tests.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from langchain_core.messages import AIMessageChunk


def content_as_text(content: Any) -> str:
    """Message content as plain text: a string, or a list of ``{"text": ...}`` parts."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            item["text"]
            for item in content
            if isinstance(item, dict) and isinstance(item.get("text"), str)
        )
    return ""


@dataclass(frozen=True)
class ModelReply:
    """What one model turn said: prose, requested tool calls, or both."""

    text: str
    tool_calls: list[dict[str, Any]] = field(default_factory=list)


def assemble_tool_calls(chunks: list[AIMessageChunk]) -> list[dict[str, Any]]:
    """Stitch tool calls out of streamed ``tool_call_chunks``.

    Deltas are grouped by ``index``; the first fragment carries id and name,
    the rest are argument-string fragments. Arguments are parsed only after
    every fragment has arrived -- a half-JSON argument is never executed. If
    the concatenation is not valid JSON, the raw string is passed on and the
    validation layer turns it into a corrective INVALID_ARGS message.
    """
    by_index: dict[int, dict[str, Any]] = {}
    for chunk in chunks:
        for delta in chunk.tool_call_chunks:
            index = delta.get("index")
            if index is None:
                index = len(by_index)
            entry = by_index.setdefault(index, {"name": None, "id": None, "args": ""})
            if delta.get("name") and not entry["name"]:
                entry["name"] = delta["name"]
            if delta.get("id") and not entry["id"]:
                entry["id"] = delta["id"]
            entry["args"] += delta.get("args") or ""

    calls: list[dict[str, Any]] = []
    for index in sorted(by_index):
        entry = by_index[index]
        if not entry["name"]:
            continue
        raw = entry["args"]
        try:
            args: Any = json.loads(raw) if raw.strip() else {}
        except ValueError:
            args = raw
        calls.append(
            {
                "name": entry["name"],
                "args": args,
                "id": entry["id"] or f"call_{index}",
            }
        )
    return calls


def _normalize_calls(raw_calls: Any) -> list[dict[str, Any]]:
    """Shape ``AIMessage.tool_calls`` (native or parsed) into the loop's dicts."""
    calls: list[dict[str, Any]] = []
    for i, call in enumerate(raw_calls or []):
        if not isinstance(call, dict) or not call.get("name"):
            continue
        calls.append(
            {
                "name": call["name"],
                "args": call.get("args") if isinstance(call.get("args"), dict) else call.get("args") or {},
                "id": call.get("id") or f"call_{i}",
            }
        )
    return calls


async def call_model(model: Any, messages: list, tools: list[dict[str, Any]]) -> ModelReply:
    """One non-streaming model call with tools bound (evals, probes)."""
    bound = model.bind_tools(tools) if tools else model
    reply = await bound.ainvoke(messages)
    return ModelReply(
        text=content_as_text(reply.content),
        tool_calls=_normalize_calls(getattr(reply, "tool_calls", None)),
    )
