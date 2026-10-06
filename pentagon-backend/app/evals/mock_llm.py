"""A deterministic stand-in for the NVIDIA chat model.

Automated tests and the eval harness never touch the real API: there is no key
to spend and no network to depend on. The mock speaks exactly the surface the
agent loop uses -- ``bind_tools``, ``ainvoke``, ``astream`` -- and its
``astream`` fragments each scripted turn into small content chunks and
per-index ``tool_call_chunks`` deltas, which is the shape the
OpenAI-compatible stream actually produces. Anything that assembles tool calls
therefore passes through this fragmentation before it meets production.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import AIMessage, AIMessageChunk, BaseMessage

_FRAGMENT_SIZE = 3


@dataclass(frozen=True)
class ScriptedTurn:
    """One model response, played in the order the loop requests turns.

    ``text`` is the prose; ``tool_calls`` is a tuple of
    ``{"name": ..., "args": {...}, "id": ...}`` dicts; ``error`` makes the
    call raise (transient-error and 429 tests script their failures here).
    A turn with neither text nor tool_calls is a bare stop.
    """

    text: str = ""
    tool_calls: tuple[dict[str, Any], ...] = ()
    error: Exception | None = None


def _fragment(text: str, size: int = _FRAGMENT_SIZE) -> list[str]:
    if not text:
        return []
    return [text[i : i + size] for i in range(0, len(text), size)]


class MockLLM:
    """A scripted model: turns play in order, prompts and bindings are recorded."""

    def __init__(self, script: Sequence[ScriptedTurn]) -> None:
        self._script = list(script)
        self._cursor = 0
        self.prompts: list[list[BaseMessage]] = []
        self.bound_tools: list[list[dict[str, Any]]] = []

    @property
    def calls(self) -> int:
        """How many times the model was invoked (the budget's unit of spend)."""
        return len(self.prompts)

    def bind_tools(self, tools: Any, **_kwargs: Any) -> "MockLLM":
        self.bound_tools.append(list(tools))
        return self

    def _next(self, messages: Any) -> ScriptedTurn:
        self.prompts.append(list(messages))
        if self._cursor >= len(self._script):
            # Out of script: a bare final answer, so a mis-wired loop ends
            # instead of spinning a test into its timeout.
            return ScriptedTurn(text="")
        turn = self._script[self._cursor]
        self._cursor += 1
        return turn

    async def ainvoke(
        self, messages: Any, config: Any = None, **_kwargs: Any
    ) -> AIMessage:
        turn = self._next(messages)
        if turn.error is not None:
            raise turn.error
        return AIMessage(content=turn.text, tool_calls=list(turn.tool_calls))

    async def astream(
        self, messages: Any, config: Any = None, **_kwargs: Any
    ) -> AsyncIterator[AIMessageChunk]:
        turn = self._next(messages)
        if turn.error is not None:
            raise turn.error
        emitted = False
        for piece in _fragment(turn.text):
            emitted = True
            yield AIMessageChunk(content=piece)
        for index, call in enumerate(turn.tool_calls):
            args_json = json.dumps(call.get("args", {}), separators=(",", ":"))
            # OpenAI sends id and name once, on the first delta of each call;
            # everything after is an argument fragment the consumer has to
            # concatenate per index. Reproduce exactly that.
            first = True
            for piece in _fragment(args_json, size=4):
                emitted = True
                yield AIMessageChunk(
                    content="",
                    tool_call_chunks=[
                        {
                            "name": call["name"] if first else None,
                            "args": piece,
                            "id": call.get("id") if first else None,
                            "index": index,
                            "type": "tool_call_chunk",
                        }
                    ],
                )
                first = False
        if not emitted:
            yield AIMessageChunk(content="")
