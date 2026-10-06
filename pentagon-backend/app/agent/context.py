"""Context management: keep the window small, keep the facts reachable.

Big tool results are stored in full and handed over as a head excerpt plus a
paging handle, so a 200 KB page never enters the model's context whole -- the
model scrolls with ``read_result``. History is compacted when it outgrows its
share of the budget: recent turns verbatim, older tool outputs masked to
one-line stubs, older turns summarized in one cached call.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from langchain_core.messages import (
    AIMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)

_HEAD_CHARS = 6_000
_STORE_TTL_SECONDS = 1_800
_STORE_LIMIT = 64
_CHARS_PER_TOKEN = 4.0  # cl100k-approximate; a conservative over-estimate for prose


def estimate_tokens(text: str) -> int:
    """A conservative token estimate: chars / 4, never fewer than the words."""
    if not text:
        return 0
    return max(int(len(text) / _CHARS_PER_TOKEN), len(text.split()) // 2 + 1)


@dataclass(frozen=True)
class StoredResult:
    handle: str
    tool: str
    text: str
    created_at: float
    total_chars: int


class ScratchStore:
    """Full tool results too big for the context, addressable by handle."""

    @staticmethod
    def head_chars() -> int:
        """The excerpt size a stored result shows inline."""
        return _HEAD_CHARS

    def __init__(self) -> None:
        self._results: dict[str, StoredResult] = {}
        self._counter = 0

    def store(self, tool: str, result_text: str) -> StoredResult | None:
        """Store a full result; ``None`` when it is small enough to skip."""
        if len(result_text) <= _HEAD_CHARS:
            return None
        self._counter += 1
        handle = f"res_{self._counter:04x}_{int(time.monotonic() * 1000) % 100_000:05d}"
        stored = StoredResult(
            handle=handle,
            tool=tool,
            text=result_text,
            created_at=time.monotonic(),
            total_chars=len(result_text),
        )
        if len(self._results) >= _STORE_LIMIT:
            oldest = min(self._results, key=lambda k: self._results[k].created_at)
            self._results.pop(oldest, None)
        self._results[handle] = stored
        return stored

    def page(self, handle: str, offset: int = 0, limit: int = 4_000) -> dict[str, Any] | None:
        """One window into a stored result."""
        stored = self._results.get(handle)
        if stored is None or stored.created_at + _STORE_TTL_SECONDS < time.monotonic():
            if stored is not None and stored.created_at + _STORE_TTL_SECONDS < time.monotonic():
                self._results.pop(handle, None)
            return None
        offset = max(0, offset)
        window = stored.text[offset : offset + limit]
        return {
            "handle": handle,
            "tool": stored.tool,
            "offset": offset,
            "total_chars": stored.total_chars,
            "has_more": offset + limit < stored.total_chars,
            "text": window,
        }

    def search(self, handle: str, query: str) -> dict[str, Any] | None:
        """Lines of a stored result matching a query, with 0-based line numbers."""
        stored = self._results.get(handle)
        if stored is None:
            return None
        needle = query.strip().lower()
        if not needle:
            return {"handle": handle, "total_chars": stored.total_chars, "matches": []}
        matches = []
        for line_number, line in enumerate(
            stored.text.splitlines(), start=1
        ):
            if needle in line.lower():
                matches.append({"line": line_number, "text": line[:300]})
            if len(matches) >= 20:
                break
        return {"handle": handle, "total_chars": stored.total_chars, "matches": matches}

    def active_handles(self) -> int:
        return len(self._results)


class ToolScratchNote:
    """What replaces an oversized ToolMessage in the model's context."""

    def __init__(self, tool: str, head: str, stored: StoredResult) -> None:
        self.tool = tool
        self.head = head
        self.stored = stored

    def as_content(self) -> str:
        return (
            f"[{self.tool} returned {self.stored.total_chars} characters; showing the first"
            f" {_HEAD_CHARS}]. Use read_result(handle={self.stored.handle!r}) to read more:"
            f" {self.head}"
        )


class ContextBudget:
    """Share of the model's context, split per the upgrade prompt's ratios.

    System + tools <= 20%, history <= 35%, tool results <= 35%, 10% reserved
    for the answer. Counts are taken on the *actual transcript sent*, so
    oversized anything is compacted before it is sent, not measured and sighed
    at.
    """

    def __init__(self, max_context: int = 32_000) -> None:
        self.max_context = max_context

    def counts(self, messages: list[BaseMessage]) -> dict[str, int]:
        system_tokens = 0
        history_tokens = 0
        tool_tokens = 0
        for position, message in enumerate(messages):
            text = str(getattr(message, "content", ""))
            tokens = estimate_tokens(text)
            if position == 0 and isinstance(message, SystemMessage):
                system_tokens += tokens
            elif isinstance(message, ToolMessage):
                tool_tokens += tokens
            else:
                history_tokens += tokens
        return {
            "system": system_tokens,
            "history": history_tokens,
            "tool": tool_tokens,
            "total": system_tokens + history_tokens + tool_tokens,
            "budget_total": int(self.max_context * 0.9),  # 10% answer reserve
        }


def _message_text(message: BaseMessage) -> str:
    return str(getattr(message, "content", ""))


def _mask_tool_result(content: str) -> str:
    """The one-line stub an old tool result becomes after compaction."""
    first_line = content.strip().splitlines()[0] if content.strip() else "(empty result)"
    return f"[tool result omitted - was: {first_line[:120]}]"


def compact_history(
    messages: list[BaseMessage],
    *,
    keep_recent: int = 6,
    max_history_tokens: int | None = None,
) -> list[BaseMessage]:
    """System + recent turns verbatim; older tool results masked.

    Deterministic and free (no LLM call): older ToolMessages become one-line
    stubs so stale 20 KB results stop weighing on every following call. When
    ``max_history_tokens`` is still exceeded after masking, the oldest
    non-system messages are dropped entirely until under budget -- the
    summary-on-demand call is a T12 refinement, correctness does not need it.
    """
    if not messages:
        return messages
    system = messages[0] if isinstance(messages[0], SystemMessage) else None
    rest = messages[1:] if system else list(messages)

    keep_count = min(keep_recent, len(rest))
    recent = rest[-keep_count:]
    older = rest[:-keep_count] if keep_count < len(rest) else []

    compacted: list[BaseMessage] = []
    if system:
        compacted.append(system)
    for message in older:
        if isinstance(message, ToolMessage):
            content = _message_text(message)
            compacted.append(
                ToolMessage(
                    content=_mask_tool_result(content),
                    tool_call_id=getattr(message, "tool_call_id", "") or "compacted",
                )
            )
        elif isinstance(message, AIMessage):
            compacted.append(
                AIMessage(
                    content=_message_text(message)[:500],
                    tool_calls=getattr(message, "tool_calls", None) or [],
                )
            )
        else:
            compacted.append(
                HumanMessage(content=_message_text(message)[:500])
            )
    compacted.extend(recent)

    if max_history_tokens is not None:
        while True:
            history_tokens = sum(
                estimate_tokens(_message_text(message))
                for message in compacted
                if message is not system
            )
            if history_tokens <= max_history_tokens or len(compacted) <= 1:
                break
            drop = compacted[1] if system else compacted[0]
            compacted.remove(drop)
    return compacted
