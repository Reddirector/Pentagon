"""Permission/autonomy control for the LangGraph chat flow.

Every tool call the chat graph wants to make is classified into exactly one
risk category. A user controls the autonomy level *per category*, not globally,
so web search can be fully automatic while shell commands always ask.

This module is the single source of truth for:

* the six fixed risk categories (``RiskCategory``)
* the four autonomy levels (``AutonomyLevel``)
* the documented defaults and the three preset bundles
* human-readable labels/descriptions for every category
* the ``arguments_summary`` helper that turns a tool call's arguments into a
  short, human-readable line for the audit log

The actual enforcement lives in ``permission_gate`` in ``chat_graph``, and the
persistence lives in the ``autonomy_settings`` / ``per_tool_overrides`` /
``action_audit_log`` tables in ``db.models``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

# ---------------------------------------------------------------------------
# Risk categories — fixed enum. Every tool / MCP capability MUST declare one.
# ---------------------------------------------------------------------------

RiskCategory = Literal[
    "read_only_info",
    "external_write",
    "external_destructive",
    "local_shell",
    "local_filesystem_write",
    "financial_or_irreversible",
]

VALID_CATEGORIES: frozenset[RiskCategory] = frozenset({
    "read_only_info",
    "external_write",
    "external_destructive",
    "local_shell",
    "local_filesystem_write",
    "financial_or_irreversible",
})

# ---------------------------------------------------------------------------
# Autonomy levels — per-category control.
# ---------------------------------------------------------------------------

AutonomyLevel = Literal[
    "always_ask",
    "ask_first_time",
    "auto_approve",
    "never_allow",
]

VALID_LEVELS: frozenset[AutonomyLevel] = frozenset({
    "always_ask",
    "ask_first_time",
    "auto_approve",
    "never_allow",
})

DECISION = Literal[
    "auto_approved",
    "user_approved",
    "user_denied",
    "blocked_never_allow",
]

VALID_DECISIONS: frozenset[DECISION] = frozenset({
    "auto_approved",
    "user_approved",
    "user_denied",
    "blocked_never_allow",
})


# ---------------------------------------------------------------------------
# Default on first run: read-only is automatic; everything else asks.
# ---------------------------------------------------------------------------

DEFAULT_LEVEL_FOR_CATEGORY: dict[RiskCategory, AutonomyLevel] = {
    "read_only_info": "auto_approve",
    "external_write": "always_ask",
    "external_destructive": "always_ask",
    "local_shell": "always_ask",
    "local_filesystem_write": "always_ask",
    "financial_or_irreversible": "always_ask",
}


# ---------------------------------------------------------------------------
# Presets — each fills all six categories at once; hand-editing after is fine.
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Preset:
    """A named bundle of per-category autonomy levels."""

    name: str
    description: str
    levels: dict[RiskCategory, AutonomyLevel]


PRESETS: dict[str, Preset] = {
    "cautious": Preset(
        name="Cautious",
        description="Ask before everything except read-only lookups.",
        levels={
            "read_only_info": "auto_approve",
            "external_write": "always_ask",
            "external_destructive": "always_ask",
            "local_shell": "always_ask",
            "local_filesystem_write": "always_ask",
            "financial_or_irreversible": "always_ask",
        },
    ),
    "balanced": Preset(
        name="Balanced",
        description="The documented defaults from §1.2.",
        levels={
            "read_only_info": "auto_approve",
            "external_write": "always_ask",
            "external_destructive": "always_ask",
            "local_shell": "always_ask",
            "local_filesystem_write": "always_ask",
            "financial_or_irreversible": "always_ask",
        },
    ),
    "autonomous": Preset(
        name="Autonomous",
        description="Auto-approve everything except destructive and financial actions.",
        levels={
            "read_only_info": "auto_approve",
            "external_write": "auto_approve",
            "external_destructive": "always_ask",
            "local_shell": "auto_approve",
            "local_filesystem_write": "auto_approve",
            "financial_or_irreversible": "always_ask",
        },
    ),
}


# ---------------------------------------------------------------------------
# Human-readable labels / descriptions per category. These are what the
# settings UI renders, NOT the raw enum names.
# ---------------------------------------------------------------------------

CATEGORY_LABELS: dict[str, str] = {
    "read_only_info": "Looking things up",
    "external_write": "Writing to outside services",
    "external_destructive": "Destroying outside-service data",
    "local_shell": "Running commands on your computer",
    "local_filesystem_write": "Changing local files",
    "financial_or_irreversible": "Payments and irreversible actions",
}

CATEGORY_DESCRIPTIONS: dict[str, str] = {
    "read_only_info": "Web search, document retrieval, reading a file, or anything that only reads.",
    "external_write": "Creating a GitHub issue, sending an email, making a calendar event, posting to Slack.",
    "external_destructive": "Deleting a GitHub issue or branch, removing a calendar event, deleting an email.",
    "local_shell": "Running a shell command, installing a package, or executing a script.",
    "local_filesystem_write": "Creating, editing, or deleting a file on this machine.",
    "financial_or_irreversible": "Anything involving payment, a purchase, or an action with no undo.",
}


# ---------------------------------------------------------------------------
# Plain-language level labels for the segmented control.
# ---------------------------------------------------------------------------

LEVEL_LABELS: dict[str, str] = {
    "always_ask": "Always ask",
    "ask_first_time": "Ask once per session",
    "auto_approve": "Auto-approve",
    "never_allow": "Never allow",
}

LEVEL_DESCRIPTIONS: dict[str, str] = {
    "always_ask": "Every call pauses and waits for your approval before running.",
    "ask_first_time": "The first call to each tool asks; later calls to that same tool auto-approve this session.",
    "auto_approve": "Never asks. Runs immediately and logs it.",
    "never_allow": "Calls in this category are rejected before they run.",
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def resolve_level(
    category: RiskCategory,
    user_settings: dict[RiskCategory, AutonomyLevel] | None,
) -> AutonomyLevel:
    """The effective autonomy level for *category* given a user's saved settings.

    *user_settings* is the row from ``autonomy_settings`` keyed by category.
    Missing categories fall back to ``DEFAULT_LEVEL_FOR_CATEGORY`` so a brand-new
    user has the documented defaults without any row.
    """
    if user_settings is None:
        return DEFAULT_LEVEL_FOR_CATEGORY[category]
    return user_settings.get(category, DEFAULT_LEVEL_FOR_CATEGORY[category])


def is_ask_level(level: AutonomyLevel) -> bool:
    """True for levels that pause the graph for a human decision."""
    return level in ("always_ask", "ask_first_time")


def is_block_level(level: AutonomyLevel) -> bool:
    """True for levels that reject before execution."""
    return level == "never_allow"


def is_auto_level(level: AutonomyLevel) -> bool:
    """True for levels that run unattended."""
    return level in ("auto_approve",)


def _safe_str(value: Any, max_len: int = 60) -> str:
    """A compact, safe string for an argument value in an audit summary."""
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    text = str(value)
    # Collapse obvious long noise.
    if len(text) > max_len:
        text = text[:max_len - 3] + "..."
    return text


def tier_to_category(tier: str) -> RiskCategory:
    """Map an agent-layer Tier onto a Pentagon risk category.

    Used by the MCP bridge (which builds ToolSpecs) and by the permission gate
    when it needs to classify a tool it only knows by tier.
    """
    return {
        "read": "read_only_info",
        "write": "external_write",
        "destructive": "external_destructive",
        "external_send": "external_write",
    }.get(tier, "read_only_info")


def arguments_summary(
    tool_name: str,
    args: dict[str, Any],
    *,
    max_len: int = 200,
) -> str:
    """A short, human-readable summary of a tool call's arguments.

    This is what goes into ``action_audit_log.arguments_summary``. It is
    deliberately *not* the raw payload: secrets, full command output, and
    large JSON blobs do not belong in an audit table.

    The shape is::

        run_shell_command(command="git status")
    """
    parts: list[str] = []
    for key, value in args.items():
        if key in {"api_key", "key", "token", "password", "secret", "auth"}:
            parts.append(f"{key}=<redacted>")
        else:
            parts.append(f"{key}={_safe_str(value)}")
    args_text = ", ".join(parts)
    if len(args_text) > max_len:
        args_text = args_text[:max_len - 3] + "..."
    return f"{tool_name}({args_text})" if args_text else tool_name
