"""verify: did the final answer stay inside the evidence this turn gathered?

Two layers, deliberately:

- ``verify_answer`` is deterministic and always runs when the turn gathered
  sources: every ``[n]`` in the answer must resolve to a gathered source,
  and every URL or domain the answer mentions must come from a gathered
  source. It never rewrites the answer -- it attaches a verdict the loop
  streams on the ``done`` event and records in the trace, so grounding is
  visible instead of assumed.
- ``repair`` makes one bounded model call to rewrite an answer that failed
  verification: unsupported citations are dropped, unsupported claims are
  hedged or removed, and the rewrite is verified again (one pass, never a
  loop). The caller spends it from the turn's own budget, so verification
  can never outgrow the answer it checks.

``gather_sources`` walks executed tool results (data, not the compacted
text the model saw) and collects anything shaped like ``{url, title}``
across web_search, fetch_url, browse_page and deep_research without
depending on any one of their schemas.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any
from urllib.parse import urlparse

_CITATION = re.compile(r"\[(\d{1,3})\]")
# Bare domains/URLs the answer leans on: anything with a dot and a plausible
# TLD, so "example.com/path" counts even outside markdown syntax.
_MENTION = re.compile(r"(?:https?://[^\s)\]>]+|[a-z0-9-]+\.[a-z]{2,}(?:/[^\s)\]>]*)?)", re.I)
_TLD_OK = re.compile(r"^[a-z]{2,24}$", re.I)

_REPAIR_INSTRUCTIONS = (
    "Rewrite the answer so it cites ONLY the numbered sources provided and "
    "removes or clearly hedges every claim the sources do not support. Keep "
    "the user's language and length. Output only the rewritten answer."
)


@dataclass
class Verification:
    """The grounding verdict, attached to the turn's done event."""

    ok: bool
    problems: list[str] = field(default_factory=list)
    sources: int = 0
    citations: list[int] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "problems": self.problems,
            "sources": self.sources,
            "citations": self.citations,
        }


def _walk_urls(data: Any) -> list[tuple[str, str]]:
    """Every (url, title) pair hidden anywhere in a tool result's data."""
    found: list[tuple[str, str]] = []
    if isinstance(data, dict):
        url = data.get("url")
        if isinstance(url, str) and url.startswith(("http://", "https://")):
            found.append((url, str(data.get("title") or "")))
        for value in data.values():
            found.extend(_walk_urls(value))
    elif isinstance(data, list):
        for item in data:
            found.extend(_walk_urls(item))
    return found


def gather_sources(results: list[tuple[str, Any]]) -> list[dict[str, str]]:
    """Executed (tool_name, ToolResult) pairs -> deduped {url, title} rows.

    Failures contribute nothing: an error page is not evidence, and a
    denied call never became ground truth.
    """
    rows: list[dict[str, str]] = []
    seen: set[str] = set()
    for _tool, result in results:
        if result is None or not result.ok:
            continue
        for url, title in _walk_urls(result.data):
            if url in seen:
                continue
            seen.add(url)
            rows.append({"url": url, "title": title or url})
    return rows


def _host(url: str) -> str:
    try:
        return (urlparse(url).hostname or "").lower()
    except ValueError:
        return ""


def _mentions(answers_text: str) -> set[str]:
    """Hosts (and bare TLD-checked tokens) the answer leans on."""
    hosts: set[str] = set()
    for match in _MENTION.finditer(answers_text):
        token = match.group(0).rstrip(".,;:")
        if token.startswith(("http://", "https://")):
            host = _host(token)
            if host:
                hosts.add(host)
                continue
        hostpart = token.split("/", 1)[0].lower()
        suffix = hostpart.rsplit(".", 1)[-1]
        if _TLD_OK.match(suffix) and "." in hostpart:
            hosts.add(hostpart)
    return hosts


def verify_answer(answer: str, sources: list[dict[str, str]]) -> Verification:
    """Deterministic grounding checks; never raises, never rewrites."""
    known_hosts = {host for host in (_host(row["url"]) for row in sources) if host}
    citations = sorted({int(n) for n in _CITATION.findall(answer)})
    problems: list[str] = []

    if not answer.strip():
        return Verification(ok=False, problems=["the final answer is empty"], sources=len(sources))

    for citation in citations:
        if citation < 1 or citation > len(sources):
            problems.append(
                f"the answer cites [{citation}], but only"
                f" [1]-[{max(len(sources), 1)}] were gathered"
            )

    for host in sorted(_mentions(answer)):
        if host in known_hosts:
            continue
        # A cited source's host covers the answer's mention of it; an
        # uncited host means the answer leaned on something not gathered.
        if not any(host == known or host.endswith("." + known) for known in known_hosts):
            problems.append(f"the answer mentions {host}, which was not among the gathered sources")

    if sources and not citations:
        problems.append(
            f"the answer cites none of the {len(sources)} source(s) gathered this turn"
        )

    return Verification(
        ok=not problems,
        problems=problems,
        sources=len(sources),
        citations=citations,
    )


async def repair(
    model: Any,
    *,
    answer: str,
    sources: list[dict[str, str]],
    verification: Verification,
    budget: Any = None,
) -> str:
    """One bounded rewrite of an answer that failed verification.

    Spends the caller's budget when one is given (BudgetExceeded propagates
    so the loop can keep the original answer); the rewrite is verified again
    and returned regardless -- one pass, never a loop.
    """
    from app.agent.llm import call_model

    if budget is not None:
        budget.spend_llm_call()
    numbered = "\n".join(
        f"[{i}] {row['title']} ({row['url']})"
        for i, row in enumerate(sources, start=1)
    )
    problems = "\n".join(f"- {problem}" for problem in verification.problems)
    messages = [
        {
            "role": "system",
            "content": _REPAIR_INSTRUCTIONS,
        },
        {
            "role": "user",
            "content": (
                f"Sources gathered this turn:\n{numbered}\n\n"
                f"Verification found:\n{problems}\n\n"
                f"Answer to rewrite:\n{answer}"
            ),
        },
    ]
    reply = await call_model(model, messages, [])
    rewritten = str(reply.text or "").strip()
    return rewritten or answer
