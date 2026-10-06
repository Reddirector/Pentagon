"""Capability probing: never assume a model can call tools -- ask it.

Three cheap requests per model, run once and cached in the ``model_capabilities``
table: does it return a well-formed tool call when one is obviously needed,
can it return two independent calls in one turn, and does it answer directly
when no tool is needed. The result drives the model picker badge
(Strong / Basic / Prompted-only) and, in T12, the routing decisions.

Probing runs against the real model with the user's key on first selection
(~3 requests). The probe itself is unit-tested against the mock LLM; live
model behavior lands under Needs live verification in the final report.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from langchain_core.messages import HumanMessage

from app.agent.llm import call_model
from app.db.models import ModelCapabilities
from app.db.session import SessionLocal
from app.tools.get_current_time import TOOL_SPEC as _TIME_SPEC

_TIME_SCHEMA = {
    "type": "function",
    "function": {
        "name": _TIME_SPEC.name,
        "description": _TIME_SPEC.description,
        "parameters": _TIME_SPEC.parameters,
    },
}
_TWO_TOOLS = [
    _TIME_SCHEMA,
    {
        "type": "function",
        "function": {
            "name": "calculator",
            "description": "Evaluate arithmetic.",
            "parameters": {
                "type": "object",
                "properties": {"expression": {"type": "string"}},
                "required": ["expression"],
            },
        },
    },
]


class ProbeResult(dict):
    """The capability record: a dict with fixed keys, easy to store and to JSON."""

    @property
    def badge(self) -> str:
        """Strong = native + parallel; Basic = native only; Prompted-only otherwise."""
        if self.get("native_tools") and self.get("parallel_tools"):
            return "Strong"
        if self.get("native_tools"):
            return "Basic"
        return "Prompted-only"


def _calls(reply) -> list[dict[str, Any]]:
    return list(getattr(reply, "tool_calls", []) or [])


async def _probe_async(model: Any) -> ProbeResult:
    result = ProbeResult(
        native_tools=False,
        parallel_tools=False,
        vision=False,
        json_mode=False,
        max_context=None,
        probed_at=datetime.now(UTC),
    )
    # 1. Needs a tool.
    reply = await call_model(model, [HumanMessage(content="What time is it in UTC right now?")], [_TIME_SCHEMA])
    calls = _calls(reply)
    if len(calls) == 1 and calls[0]["name"] == "get_current_time":
        result["native_tools"] = isinstance(calls[0]["args"], dict)
    # 2. Two independent needs at once.
    if result["native_tools"]:
        reply = await call_model(
            model,
            [HumanMessage(content="What time is it, and what is 12 times 9? Answer both.")],
            _TWO_TOOLS,
        )
        result["parallel_tools"] = len(_calls(reply)) >= 2
    return result


def probe_and_cache(model: Any, model_id: str) -> ProbeResult:
    """Probe synchronously and persist under ``model_id``."""
    result = _run_async(_probe_async(model))
    _cache(model_id, result)
    return result


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)


def _cache(model_id: str, result: ProbeResult) -> None:
    with SessionLocal() as db:
        row = db.get(ModelCapabilities, model_id)
        if row is None:
            row = ModelCapabilities(model_id=model_id)
            db.add(row)
        row.native_tools = bool(result.get("native_tools"))
        row.parallel_tools = bool(result.get("parallel_tools"))
        row.vision = bool(result.get("vision", False))
        row.json_mode = bool(result.get("json_mode", False))
        row.max_context = result.get("max_context")
        row.probed_at = result.get("probed_at")
        db.commit()


def cached_capabilities(model_id: str) -> ProbeResult | None:
    """The stored probe result for this model, if it has ever been probed."""
    with SessionLocal() as db:
        row = db.get(ModelCapabilities, model_id)
        if row is None:
            return None
        return ProbeResult(
            native_tools=bool(row.native_tools),
            parallel_tools=bool(row.parallel_tools),
            vision=bool(row.vision),
            json_mode=bool(row.json_mode),
            max_context=row.max_context,
            probed_at=row.probed_at,
        )


def ensure_probed(model: Any, model_id: str, *, refresh: bool = False) -> ProbeResult:
    """The capabilities for ``model_id``, probing and caching on first use."""
    if not refresh:
        cached = cached_capabilities(model_id)
        if cached is not None:
            return cached
    return probe_and_cache(model, model_id)
