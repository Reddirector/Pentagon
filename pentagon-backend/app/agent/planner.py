"""The visible task plan: a checklist the model maintains, not its reasoning.

The plan is a transparency feature -- the user sees what the agent intends
and where it stands. The model proposes the full list each time it calls
``update_plan``; this module normalizes it so the invariants hold no matter
what the model sent: at most 7 steps, statuses from the fixed set, exactly
one ``in_progress`` (the first wins, the rest are demoted to ``pending``),
and non-empty step text. Raw chain-of-thought never appears here.
"""

from __future__ import annotations

from typing import Any

_STATUSES = ("pending", "in_progress", "done", "blocked")
_MAX_STEPS = 7
_MAX_STEP_CHARS = 200


class PlanError(ValueError):
    """The proposed plan broke a structural rule."""


def normalize_plan(raw: Any) -> list[dict[str, str]]:
    """A validated ``[{text, status}]`` list, or PlanError explaining why not."""
    if not isinstance(raw, list) or not raw:
        raise PlanError("steps must be a non-empty list of {text, status} objects.")
    if len(raw) > _MAX_STEPS:
        raise PlanError(
            f"a plan has at most {_MAX_STEPS} steps; {len(raw)} were given."
        )
    steps: list[dict[str, str]] = []
    for index, entry in enumerate(raw):
        if not isinstance(entry, dict):
            raise PlanError(f"step {index + 1} must be an object with text and status.")
        text = entry.get("text")
        status = entry.get("status") or "pending"
        if not isinstance(text, str) or not text.strip():
            raise PlanError(f"step {index + 1} has no text.")
        if len(text) > _MAX_STEP_CHARS:
            raise PlanError(f"step {index + 1} text is over {_MAX_STEP_CHARS} characters.")
        if status not in _STATUSES:
            raise PlanError(
                f"step {index + 1} status {status!r} is not one of: {', '.join(_STATUSES)}."
            )
        steps.append({"text": text.strip(), "status": status})

    in_progress = [step for step in steps if step["status"] == "in_progress"]
    for extra in in_progress[1:]:
        extra["status"] = "pending"
    return steps


def plan_summary(steps: list[dict[str, str]]) -> str:
    """A one-line rendering for traces and status events."""
    done = sum(1 for step in steps if step["status"] == "done")
    current = next((step["text"] for step in steps if step["status"] == "in_progress"), "")
    arrow = f" -- now: {current}" if current else ""
    return f"{done}/{len(steps)} done{arrow}"
