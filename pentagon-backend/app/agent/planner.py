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
    if isinstance(raw, str):
        stripped = raw.strip()
        parsed = None
        if stripped.startswith("[") or stripped.startswith("{"):
            try:
                import json
                parsed = json.loads(stripped)
            except Exception:
                try:
                    import ast
                    parsed = ast.literal_eval(stripped)
                except Exception:
                    pass
        if isinstance(parsed, list):
            raw = parsed
        elif isinstance(parsed, dict):
            raw = parsed.get("steps") or parsed.get("plan") or parsed.get("tasks") or parsed.get("checklist") or list(parsed.values())

    if isinstance(raw, dict):
        raw = raw.get("steps") or raw.get("plan") or raw.get("tasks") or raw.get("checklist") or list(raw.values())

    if not isinstance(raw, list) or not raw:
        raise PlanError("steps must be a non-empty list of {text, status} objects.")
    if len(raw) > _MAX_STEPS:
        raw = raw[:_MAX_STEPS]

    steps: list[dict[str, str]] = []
    for index, entry in enumerate(raw):
        if isinstance(entry, str):
            entry = {"text": entry, "status": "in_progress" if index == 0 else "pending"}
        elif not isinstance(entry, dict):
            entry = {"text": str(entry), "status": "pending"}

        text = str(entry.get("text") or "").strip()
        if not text:
            text = f"Step {index + 1}"
        if len(text) > _MAX_STEP_CHARS:
            text = text[:_MAX_STEP_CHARS]

        status = entry.get("status")
        if status not in _STATUSES:
            status = "pending"
        steps.append({"text": text, "status": status})

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
