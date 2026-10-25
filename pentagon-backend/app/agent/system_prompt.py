"""The system prompt as a file, not a string buried in code.

``app/agent/prompts/system.md`` is what a turn opens with when the caller
does not pass its own prompt (tests and specialized routes do pass one).
Keeping it in a file means prompt edits are reviewable diffs with real
line breaks, and the loader is the single place that decides the default.
"""

from __future__ import annotations

from pathlib import Path

PROMPT_PATH = Path(__file__).resolve().parent / "prompts" / "system.md"

# Fallback used only if the file is missing (a broken install): an empty
# prompt would make the model answer as a raw completion, which is worse
# than a blunt statement of the problem.
_FALLBACK = (
    "You are Pentagon, a personal AI assistant. Answer plainly, use tools "
    "to check anything you cannot know, and never invent tool results."
)


def default_system_prompt(model_id: str | None = None) -> str:
    """The contents of prompts/system.md (or a blunt fallback), contextualized with model identity."""
    try:
        text = PROMPT_PATH.read_text(encoding="utf-8")
    except OSError:
        text = _FALLBACK
    base = text.strip() or _FALLBACK
    if model_id:
        model_context = (
            f"\n\n# Active Model & Identity\n"
            f"- You are running on model: `{model_id}`.\n"
            f"- Whenever asked 'Who are you?', 'What are you?', or about your identity, you MUST always reply:\n"
            f"  \"I'm Pentagon and running on {model_id}\"\n"
        )
        return f"{base}{model_context}"
    return base
