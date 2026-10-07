"""Which skills load for one turn — and exactly what gets injected.

Matching runs against the light frontmatter index only (no model call, no
NVIDIA budget spent — the same local-first rule every Pentagon matcher
follows), using the user's latest message plus a little recent history so a
follow-up like "now turn it into a report" still counts as a document
request. The selected bodies are shaped here and handed back as a string
for this turn's prompt; the caller never puts them into the stored
transcript, so nothing loads twice and thread history stays lean.

Disabled skills are excluded *before* the cap, not deprioritised: off means
off. At most ``MAX_SKILLS_PER_TURN`` bodies load, and every turn logs
``skills fired: [...]`` — empty list included — which is how "matched
nothing" is verified rather than guessed.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.db.models import SkillSetting
from app.db.session import SessionLocal
from app.skills.loader import (
    MAX_SKILLS_PER_TURN,
    SkillFormatError,
    get_index,
)

logger = logging.getLogger(__name__)

# How much of the conversation the matcher may see. The latest message is
# what counts most; history only prevents a pronoun from matching nothing.
_RECENT_MESSAGES = 4
_LATEST_MESSAGE_CHARS = 800
_HISTORY_CHAR_BUDGET = 700


@dataclass(frozen=True)
class TurnSkills:
    instructions: str  # what to inject for this turn ("" when nothing fired)
    fired: tuple[str, ...]


def disabled_skill_ids(user_id: str) -> set[str]:
    """Skill ids this user has switched off (absence of a row = enabled)."""
    with SessionLocal() as db:
        rows = db.scalars(
            select(SkillSetting.skill_id).where(
                SkillSetting.user_id == user_id,
                SkillSetting.enabled.is_(False),
            )
        )
        return set(rows)


def available_tool_names(*, command_tool_enabled: bool) -> frozenset[str]:
    """Tools Pentagon can actually offer right now, for the missing-capability
    note. Mirrors the graph's own gating for the shell tools so the note is
    honest about *this* session, not about the ideal configuration.

    The chat_graph import is deferred on purpose: chat_graph imports this
    module, and a top-level import back would be a cycle.
    """
    from app.agent.bootstrap import build_registry
    from app.services.chat_graph import SHELL_TOOL_NAME
    from app.services.desktop_actions import DESKTOP_TOOL_NAME
    from app.services.location import LOCATION_TOOL_NAME

    names = set(build_registry().names())
    if command_tool_enabled and settings.command_tool_enabled:
        names.add(SHELL_TOOL_NAME)
        if settings.desktop_actions_enabled:
            names.add(DESKTOP_TOOL_NAME)
        if settings.location_enabled:
            names.add(LOCATION_TOOL_NAME)
    return frozenset(names)


def build_match_text(user_message: str, history: list[Any]) -> str:
    """The text the matcher sees: this message first, a little history after."""
    parts = [user_message[:_LATEST_MESSAGE_CHARS]]
    budget = _HISTORY_CHAR_BUDGET
    for message in reversed(list(history[-_RECENT_MESSAGES:])):
        if budget <= 0:
            break
        content = getattr(message, "content", "")
        if isinstance(content, list):
            content = " ".join(
                chunk.get("text", "")
                for chunk in content
                if isinstance(chunk, dict)
            )
        if not isinstance(content, str) or not content.strip():
            continue
        piece = content[:budget]
        parts.append(piece)
        budget -= len(piece)
    return "\n".join(parts)


def _missing_note(missing: list[str]) -> str:
    joined = ", ".join(f"`{name}`" for name in missing)
    return (
        f"> Capability note: this skill assumes tool(s) that are not available "
        f"right now: {joined}. Follow the rest of the skill, but do not promise "
        "what Pentagon cannot do in this session — say plainly what is missing "
        "if it matters.\n\n"
    )


def match_for_turn(
    *,
    user_id: str,
    user_message: str,
    history: list[Any] | None = None,
    command_tool_enabled: bool = False,
) -> TurnSkills:
    """Select, cap, and render this turn's skills. Always logs what fired."""
    index = get_index()
    matches = index.search_skills(build_match_text(user_message, history or []))
    if matches and user_id:
        disabled = disabled_skill_ids(user_id)
        if disabled:
            matches = [
                match for match in matches if match.skill.skill_id not in disabled
            ]
    selected = matches[:MAX_SKILLS_PER_TURN]
    if not selected:
        logger.info("skills fired: []")
        return TurnSkills(instructions="", fired=())

    available = (
        available_tool_names(command_tool_enabled=command_tool_enabled)
        if any(match.skill.requires_tools for match in selected)
        else frozenset()
    )
    blocks: list[str] = []
    fired: list[str] = []
    for match in selected:
        skill = match.skill
        try:
            body = index.body(skill.skill_id)
        except (SkillFormatError, OSError, UnicodeDecodeError) as exc:
            # The body could disappear or break between index and load; the
            # skill then contributes nothing rather than a half-injection.
            logger.warning("skill %s body unavailable (%s); skipping", skill.skill_id, exc)
            continue
        missing = [tool for tool in skill.requires_tools if tool not in available]
        content = _missing_note(missing) + body if missing else body
        blocks.append(f"### Skill: {skill.name} (`{skill.skill_id}`)\n\n{content}")
        fired.append(skill.skill_id)

    logger.info("skills fired: %s", fired)
    return TurnSkills(instructions="\n\n".join(blocks), fired=tuple(fired))
