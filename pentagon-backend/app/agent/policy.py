"""Per-category autonomy policy for the agent loop."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from sqlalchemy import select

from app.agent.schemas import ToolSpec
from app.db.models import ActionAuditLog, AutonomySetting, PerToolOverride, new_id, utc_now
from app.db.session import SessionLocal
from app.services.autonomy import (
    DEFAULT_LEVEL_FOR_CATEGORY,
    VALID_CATEGORIES,
    arguments_summary,
    resolve_level,
)
from app.services.permissions import normalize_level


def _legacy_category_defaults(permission_level: object) -> dict[str, str]:
    """Translate the existing three-rung setting into category fallbacks.

    Explicit per-category settings override these values. This keeps the
    agent's newer policy surface consistent with users' saved global setting.
    """
    level = normalize_level(permission_level)
    if level == 1:
        return {category: "always_ask" for category in VALID_CATEGORIES}
    if level == 3:
        return {
            "read_only_info": "auto_approve",
            "external_write": "auto_approve",
            "external_destructive": "always_ask",
            "local_shell": "auto_approve",
            "local_filesystem_write": "auto_approve",
            "financial_or_irreversible": "always_ask",
        }
    return dict(DEFAULT_LEVEL_FOR_CATEGORY)


@dataclass
class AgentPermissionPolicy:
    user_id: str
    levels: dict[str, str]
    approved_tools: set[tuple[str, str]] = field(default_factory=set)

    def level_for(self, spec: ToolSpec) -> tuple[str, str]:
        """Return the saved category level and its effective level for a tool."""
        category = spec.risk_category
        configured = resolve_level(category, self.levels)
        if configured == "ask_first_time" and (spec.name, category) in self.approved_tools:
            return configured, "auto_approve"
        return configured, configured

    def remember(self, spec: ToolSpec) -> None:
        key = (spec.name, spec.risk_category)
        with SessionLocal() as db:
            row = db.get(
                PerToolOverride,
                {
                    "user_id": self.user_id,
                    "tool_name": spec.name,
                    "category": spec.risk_category,
                },
            )
            if row is None:
                db.add(
                    PerToolOverride(
                        user_id=self.user_id,
                        tool_name=spec.name,
                        category=spec.risk_category,
                        approved_this_session=True,
                    )
                )
            else:
                row.approved_this_session = True
            db.commit()
        self.approved_tools.add(key)


def load_policy(user_id: str, permission_level: object = 2) -> AgentPermissionPolicy:
    """Load category settings and user-scoped session approvals."""
    with SessionLocal() as db:
        configured_levels = {
            row.category: row.level
            for row in db.scalars(
                select(AutonomySetting).where(AutonomySetting.user_id == user_id)
            ).all()
        }
        approved = {
            (row.tool_name, row.category)
            for row in db.scalars(
                select(PerToolOverride).where(
                    PerToolOverride.user_id == user_id,
                    PerToolOverride.approved_this_session.is_(True),
                )
                ).all()
            }
    levels = _legacy_category_defaults(permission_level)
    levels.update(configured_levels)
    return AgentPermissionPolicy(user_id=user_id, levels=levels, approved_tools=approved)


def audit_decision(
    *,
    user_id: str,
    conversation_id: str,
    spec: ToolSpec,
    args: dict[str, Any],
    level: str,
    decision: str,
) -> None:
    """Persist a valid agent call decision before any execution can start."""
    with SessionLocal() as db:
        db.add(
            ActionAuditLog(
                id=new_id(),
                user_id=user_id,
                conversation_id=conversation_id,
                tool_name=spec.name,
                category=spec.risk_category,
                autonomy_level_at_time=level,
                decision=decision,
                arguments_summary=arguments_summary(spec.name, args),
                timestamp=utc_now(),
            )
        )
        db.commit()
