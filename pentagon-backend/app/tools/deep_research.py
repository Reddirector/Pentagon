"""deep_research: multi-query web research with a cited report, bounded.

The tool resolves the caller's own API key (stored key, then the server
fallback -- never one from arguments or prompts), hands the orchestrator a
hard internal budget, and maps its failures honestly: no key is a DENIED
with a Settings pointer, a missed deadline is a TIMEOUT, and an empty
search is an UPSTREAM that says so rather than a confident guess. The
report arrives untrusted, so the loop spotlights and scan-flags its
third-party text before it enters the conversation.
"""

from __future__ import annotations

from typing import Any

from app.agent import research
from app.agent.schemas import ToolContext, ToolResult, ToolSpec
from app.config import settings
from app.db.session import SessionLocal
from app.security.keys import NoKeyAvailableError, resolve_api_key

TOOL_SPEC = ToolSpec(
    name="deep_research",
    description=(
        "Research a question across multiple web searches and return a"
        " cited report: plan several angles, read the pages behind the top"
        " results, then synthesize an answer with numbered sources. Use when"
        " a question needs current, sourced information -- product"
        " comparisons, recent events, technical facts worth citing -- rather"
        " than a single lookup. Costs several searches and two model calls"
        " and can take up to a minute and a half, so do not use it for simple"
        " questions a single web_search would answer. Returns the report, the"
        " queries run, and the source list; cite sources as [1], [2]."
        ' Example: {"question": "How do the current vector databases compare'
        ' for hybrid search?"}.'
    ),
    parameters={
        "type": "object",
        "properties": {
            "question": {
                "type": "string",
                "description": (
                    "The research question, specific enough that the answer"
                    " can be cited from public sources."
                ),
            }
        },
        "required": ["question"],
    },
    tier="read",
    timeout_s=120,
    cacheable=False,
    idempotent=False,
    parallel_safe=False,
    untrusted=True,
    tags=(
        "research",
        "deep",
        "investigate",
        "report",
        "sources",
        "synthesize",
        "gather",
        "compare",
        "survey",
    ),
)


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    question = args.get("question")
    if not isinstance(question, str) or not question.strip():
        return ToolResult.failure(
            "INVALID_ARGS",
            "question must be a non-empty research question.",
            hint='Example: {"question": "State of WebGPU support in 2026?"}.',
        )
    if len(question) > research._QUESTION_CHARS:
        return ToolResult.failure(
            "INVALID_ARGS",
            f"question is {len(question)} chars;"
            f" the limit is {research._QUESTION_CHARS}.",
            hint="Narrow it to the one thing you need researched.",
        )
    try:
        with SessionLocal() as db:
            api_key = resolve_api_key(db, ctx.user_id)
    except NoKeyAvailableError:
        return ToolResult.failure(
            "DENIED",
            "Deep research needs an NVIDIA API key and this user has none.",
            hint="Add a key in Settings; research never runs on borrowed credentials.",
        )
    model = settings.default_chat_model or research.RESEARCH_MODEL_ID
    try:
        outcome = await research.research(
            question.strip(), api_key=api_key, model=model
        )
    except research.ResearchTimeout as exc:
        return ToolResult.failure(
            "TIMEOUT",
            str(exc),
            hint="Narrow the question, or gather with web_search instead.",
        )
    except research.ResearchError as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"Research could not complete: {exc}.",
            hint="Try web_search for individual lookups instead.",
        )
    except Exception as exc:
        return ToolResult.failure(
            "UPSTREAM",
            f"Research failed unexpectedly ({type(exc).__name__}).",
            hint="Nothing was written; retry or use web_search.",
        )
    return ToolResult.success(outcome)
