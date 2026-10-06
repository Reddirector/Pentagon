"""Tool retrieval: choose which tools the model sees this turn.

A model gets measurably worse as the tool list grows, so a turn never sees
more than ``MAX_TOOLS`` (12): six core tools are always on, and the rest are
scored against the user's message by lexical overlap on description and tags
(a local, deterministic scorer -- no embedding call to waste quota on), with
sticky retention for tools already used in the conversation. The exposure and
what was actually used are logged via the trace recorder, which feeds the
evals.
"""

from __future__ import annotations

import re

from app.agent.registry import ToolRegistry

CORE_TOOLS = (
    "get_current_time",
    "calculator",
    "web_search",
    "fetch_url",
    "search_documents",
    "ask_user",
)
# update_plan and read_result land with T5/T6; ask_user with T6. Until a tool
# is registered it simply cannot be selected, so this list is aspirational for
# the core and hard-filtered against what exists.

MAX_TOOLS = 12

_WORD = re.compile(r"[a-z0-9]{3,}")


def _tokens(text: str) -> set[str]:
    return set(_WORD.findall(text.lower()))


def _signal(name: str) -> float:
    """Nudge toward frequently-confused phrasings the core tools already own."""
    return 0.0


def score_tool(spec, message: str) -> float:
    """Lexical overlap between the message and a tool's description + tags."""
    message_tokens = _tokens(message)
    if not message_tokens:
        return 0.0
    spec_tokens = _tokens(spec.description) | set(spec.tags)
    overlap = len(message_tokens & spec_tokens)
    # One decisive tag hit is worth more than several incidental description hits.
    tag_tokens = set()
    for tag in spec.tags:
        tag_tokens |= _tokens(tag)
    if message_tokens & tag_tokens:
        overlap += 2
    return float(overlap)


def select_tools(
    registry: ToolRegistry,
    message: str,
    *,
    sticky: set[str] | None = None,
    docs_present: bool = False,
) -> list[str]:
    """The tool names this turn should expose, core first, capped at MAX_TOOLS."""
    available = registry.names()
    selected: list[str] = []
    for name in CORE_TOOLS:
        if name in available:
            selected.append(name)
    if docs_present and "read_document" in available and "read_document" not in selected:
        selected.append("read_document")
    if sticky:
        for name in sticky:
            if name in available and name not in selected:
                selected.append(name)

    candidates = [
        (score_tool(registry.get(name).spec, message), name)
        for name in available
        if name not in selected
    ]
    candidates.sort(key=lambda pair: (-pair[0], pair[1]))
    for score, name in candidates:
        if len(selected) >= MAX_TOOLS:
            break
        if score <= 0:
            break
        selected.append(name)
    return selected[:MAX_TOOLS]
