"""Turning the shell tool on and off, and answering its approval requests.

Two separate gates, deliberately:

* ``enabled`` is a per-user preference in the database. The user owns it, and
  it survives a restart.
*``settings.command_tool_enabled`` is the server-wide kill switch. When it is
false the model is never handed the tool at all, so a client cannot turn
shell access on for itself by flipping its own preference.

The approval endpoint is the other half of the design in
``services.command_runner``: a command that is not provably read-only waits
here for a decision, and an unanswered request times out into a denial.

The registry is reached through the module rather than imported by name, so
there is exactly one instance in the process even when a test swaps it out.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.db.session import get_db
from app.services import capability, command_runner
from app.services.permissions import (
    MAX_PERMISSION_LEVEL,
    MIN_PERMISSION_LEVEL,
    level_info,
    levels_as_list,
    normalize_level,
)


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/commands", tags=["commands"])


async def require_capability(
    x_pentagon_capability: str | None = Header(default=None),
) -> None:
    """Every route on this router needs the app's secret, not just a user_id.

    Knowing a ``user_id`` is not enough to approve a command, read what is
    waiting for a decision, or supply a location on the user's behalf. The
    token is issued by the desktop app at first run and kept in a file only the
    user can read.
    """
    if not capability.verify(x_pentagon_capability):
        raise HTTPException(
            status_code=401,
            detail=(
                "This request needs the Pentagon capability token. It proves "
                "the call came from the app rather than from someone who merely "
                "knows a user id."
            ),
        )


class CommandSettings(BaseModel):
    enabled: bool
    available: bool
    approval_timeout_seconds: float
    # Desktop control is a separate server switch, reported so the client can
    # say "this is off on the server" instead of implying the user forgot.
    desktop_available: bool
    # Location is a separate server switch too, so the client can say "this is
    # off on the server" instead of the model simply failing to answer.
    location_available: bool
    # Which rung of the approval ladder this user is on. Read from the user
    # row, and echoed back so the client never has to guess what it saved.
    permission_level: int
    # The whole ladder, so the client renders the same names, ordering and
    # wording the server enforces rather than hard-coding a second copy that
    # can drift.
    permission_levels: list[dict[str, object]]
    # The current rung's name, so a heading or badge needs no lookup table.
    permission_name: str


class CommandSettingsUpdate(BaseModel):
    enabled: bool
    # Optional so an older client that only toggles `enabled` keeps working;
    # when omitted the stored level is left exactly as it was.
    permission_level: int | None = Field(
        default=None,
        ge=MIN_PERMISSION_LEVEL,
        le=MAX_PERMISSION_LEVEL,
    )


class CommandDecision(BaseModel):
    request_id: str = Field(min_length=1, max_length=64)
    approved: bool


class CommandDecisionRequest(CommandDecision):
    """A decision always names its owner.

    ``user_id`` is carried in the body rather than the query string because this
    is the one write that can authorise something to happen: the registry
    checks it against the request's owner before resolving, so a leaked request
    id cannot be approved by somebody else.
    """

    user_id: str = Field(min_length=1, max_length=128)
    # For requests of kind "location", the client answers with coordinates
    # rather than a decision. Ignored for ordinary approvals, so the existing
    # Run it / Don't run flow is unchanged.
    value: dict[str, Any] = Field(default_factory=dict)


class CommandDecisionResponse(BaseModel):
    resolved: bool


@router.get("/settings", response_model=CommandSettings, dependencies=[Depends(require_capability)])
def read_settings(
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    level = normalize_level(user.permission_level if user is not None else None)
    return {
        # A stored True cannot override a server that has the tool switched off,
        # so `available` is the single thing the client needs to know.
        "enabled": bool(user is not None and user.command_tool_enabled),
        "available": settings.command_tool_enabled,
        "approval_timeout_seconds": settings.command_approval_timeout_seconds,
        "desktop_available": settings.desktop_actions_enabled,
        "location_available": settings.location_enabled,
        "permission_level": level,
        "permission_levels": levels_as_list(),
        "permission_name": level_info(level).name,
    }


@router.put("/settings", response_model=CommandSettings, dependencies=[Depends(require_capability)])
def update_settings(
    payload: CommandSettingsUpdate,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    if not settings.command_tool_enabled:
        raise HTTPException(
            status_code=403,
            detail="The command tool is disabled on this server.",
        )
    user = db.get(User, user_id)
    if user is None:
        user = User(id=user_id)
        db.add(user)
    user.command_tool_enabled = payload.enabled
    # Only touch the level when the client actually sent one. An older client
    # toggling `enabled` must not reset a level the user deliberately chose.
    if payload.permission_level is not None:
        user.permission_level = normalize_level(payload.permission_level)
    db.commit()
    level = normalize_level(user.permission_level)
    logger.info(
        "command tool %s user=%s level=%s",
        "enabled" if payload.enabled else "disabled",
        user_id,
        level,
    )
    return {
        "enabled": payload.enabled,
        "available": True,
        "approval_timeout_seconds": settings.command_approval_timeout_seconds,
        "desktop_available": settings.desktop_actions_enabled,
        "location_available": settings.location_enabled,
        "permission_level": level,
        "permission_levels": levels_as_list(),
        "permission_name": level_info(level).name,
    }


@router.post("/decide", response_model=CommandDecisionResponse, dependencies=[Depends(require_capability)])
def decide(payload: CommandDecisionRequest) -> dict:
    """Approve or deny a pending command.

    Returns ``resolved: false`` rather than a 404 for an unknown id: the id is
    only ever known to the client that asked for the command, and a wrong guess
    should not be able to distinguish "no such request" from "not yours".
    """
    resolved = command_runner.REGISTRY.resolve(
        payload.request_id, payload.user_id, payload.approved, payload.value or None
    )
    return {"resolved": resolved}


@router.get("/pending", dependencies=[Depends(require_capability)])
def pending(
    user_id: str = Query(min_length=1, max_length=128),
    conversation_id: str = Query(min_length=1, max_length=64),
) -> list[dict]:
    """Requests still waiting on the user, so a reconnect does not strand one."""
    return command_runner.REGISTRY.pending_for(conversation_id, user_id)