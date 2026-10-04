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

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import User
from app.db.session import get_db
from app.services import command_runner


logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/commands", tags=["commands"])


class CommandSettings(BaseModel):
    enabled: bool
    available: bool
    approval_timeout_seconds: float


class CommandSettingsUpdate(BaseModel):
    enabled: bool


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


class CommandDecisionResponse(BaseModel):
    resolved: bool


@router.get("/settings", response_model=CommandSettings)
def read_settings(
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> dict:
    user = db.get(User, user_id)
    return {
        # A stored True cannot override a server that has the tool switched off,
        # so `available` is the single thing the client needs to know.
        "enabled": bool(user is not None and user.command_tool_enabled),
        "available": settings.command_tool_enabled,
        "approval_timeout_seconds": settings.command_approval_timeout_seconds,
    }


@router.put("/settings", response_model=CommandSettings)
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
    db.commit()
    logger.info(
        "command tool %s user=%s",
        "enabled" if payload.enabled else "disabled",
        user_id,
    )
    return {
        "enabled": payload.enabled,
        "available": True,
        "approval_timeout_seconds": settings.command_approval_timeout_seconds,
    }


@router.post("/decide", response_model=CommandDecisionResponse)
def decide(payload: CommandDecisionRequest) -> dict:
    """Approve or deny a pending command.

    Returns ``resolved: false`` rather than a 404 for an unknown id: the id is
    only ever known to the client that asked for the command, and a wrong guess
    should not be able to distinguish "no such request" from "not yours".
    """
    resolved = command_runner.REGISTRY.resolve(payload.request_id, payload.user_id, payload.approved)
    return {"resolved": resolved}


@router.get("/pending")
def pending(
    user_id: str = Query(min_length=1, max_length=128),
    conversation_id: str = Query(min_length=1, max_length=64),
) -> list[dict]:
    """Requests still waiting on the user, so a reconnect does not strand one."""
    return command_runner.REGISTRY.pending_for(conversation_id, user_id)