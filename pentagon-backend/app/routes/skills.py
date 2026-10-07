"""The skills API behind Settings → Skills (§5).

List what is loaded (public + user) with each user's toggle state, flip a
toggle, and create a skill from a form. Creation is where the validation
rules live — description under the cap, at least one trigger, a risk
category the permission system actually recognises — because a manifest
that fails *there* can be reported in the form, while one that slips
through is discovered as a silent skip in the loader's warning log.

Everything is scoped by ``user_id`` like every other Pentagon route: a
foreign id gets a 404, never a confirmation that the skill exists.
"""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.db.models import SkillSetting, User
from app.db.session import get_db
from app.skills.loader import (
    DESCRIPTION_MAX_CHARS,
    RISK_CATEGORIES,
    build_manifest,
    get_index,
)
from app.skills.router import disabled_skill_ids

router = APIRouter(prefix="/api/skills", tags=["skills"])

_MAX_TRIGGERS = 12
_MAX_TRIGGER_CHARS = 60
_MAX_BODY_CHARS = 20_000
_SLUG = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG.sub("-", name.strip().lower()).strip("-")


class SkillCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    name: str = Field(min_length=1, max_length=80)
    # Pydantic's ceiling is generous on purpose: the real cap is enforced in
    # the handler, where the error can explain *why* the description is short.
    description: str = Field(min_length=1, max_length=4000)
    triggers: list[str] = Field(default_factory=list, max_length=_MAX_TRIGGERS)
    risk_category: str = "read"
    requires_tools: list[str] = Field(default_factory=list, max_length=16)
    body: str = Field(min_length=1, max_length=_MAX_BODY_CHARS)


class SkillToggle(BaseModel):
    user_id: str = Field(min_length=1, max_length=128)
    enabled: bool


def _skill_payload(skill, *, enabled: bool) -> dict[str, object]:
    return {**skill.as_dict(), "enabled": enabled}


@router.get("")
def list_skills(
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> list[dict[str, object]]:
    index = get_index()
    disabled = disabled_skill_ids(user_id)
    return [
        _skill_payload(skill, enabled=skill.skill_id not in disabled)
        for skill in index.all()
    ]


@router.patch("/{skill_id}")
def set_skill_enabled(
    skill_id: str,
    payload: SkillToggle,
    db: Session = Depends(get_db),
) -> dict[str, object]:
    if get_index().get(skill_id) is None:
        raise HTTPException(status_code=404, detail="Skill not found.")
    if db.get(User, payload.user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")
    row = db.get(SkillSetting, {"user_id": payload.user_id, "skill_id": skill_id})
    if row is None:
        if payload.enabled:
            # Enabled is the default; nothing to store until someone objects.
            return {"skill_id": skill_id, "enabled": True}
        row = SkillSetting(user_id=payload.user_id, skill_id=skill_id, enabled=False)
        db.add(row)
    else:
        row.enabled = payload.enabled
    db.commit()
    return {"skill_id": skill_id, "enabled": payload.enabled}


@router.post("", status_code=201)
def create_skill(payload: SkillCreate, db: Session = Depends(get_db)) -> dict[str, object]:
    description = " ".join(payload.description.split())
    if not description:
        raise HTTPException(status_code=422, detail="A description is required.")
    if len(description) > DESCRIPTION_MAX_CHARS:
        raise HTTPException(
            status_code=422,
            detail=(
                f"The description is the only text the model sees before loading "
                f"a skill, so it is capped at {DESCRIPTION_MAX_CHARS} characters."
            ),
        )
    triggers = [trigger.strip().lower() for trigger in payload.triggers if trigger.strip()]
    if not triggers:
        raise HTTPException(
            status_code=422,
            detail="Add at least one trigger keyword or phrase the matcher should look for.",
        )
    if payload.risk_category not in RISK_CATEGORIES:
        raise HTTPException(
            status_code=422,
            detail=(
                f"risk_category must be one of: {', '.join(sorted(RISK_CATEGORIES))} "
                "(the permission system's own categories)."
            ),
        )
    body = payload.body.strip()
    if not body:
        raise HTTPException(status_code=422, detail="The instruction body cannot be empty.")

    skill_id = slugify(payload.name)
    if not skill_id:
        raise HTTPException(
            status_code=422,
            detail="The skill name must contain letters or digits to name a folder.",
        )

    index = get_index()
    if index.get(skill_id) is not None:
        raise HTTPException(
            status_code=409,
            detail=f"A skill named {skill_id!r} already exists; pick another name.",
        )

    user = db.get(User, payload.user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found.")

    manifest = build_manifest(
        name=payload.name,
        description=description,
        triggers=triggers,
        risk_category=payload.risk_category,
        requires_tools=payload.requires_tools,
    )
    skill_dir = index.root / "user" / skill_dir_name(skill_id)
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_path = skill_dir / "SKILL.md"
    try:
        skill_path.write_text(f"---\n{manifest}---\n\n{body}\n", encoding="utf-8")
    except OSError:
        raise HTTPException(
            status_code=500, detail="Could not write the skill file."
        ) from None

    # The loader scans on access, so this is picked up on the next turn with
    # no restart; refreshing here makes the immediate list read correct too.
    index.refresh()
    skill = index.get(skill_id)
    if skill is None:
        # The file parsed into nothing the loader accepts -- report the
        # loader's own reason rather than pretending the save worked.
        skill_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=422,
            detail="The skill could not be parsed after writing; nothing was saved.",
        )
    return _skill_payload(skill, enabled=True)


def skill_dir_name(skill_id: str) -> str:
    """Folder name for a skill id. Ids are slug-shaped already, but a second
    pass means a crafted name can never traverse out of skills/user/."""
    return _SLUG.sub("-", skill_id.strip().lower()).strip("-") or "skill"


@router.delete("/{skill_id}", status_code=204)
def delete_skill(
    skill_id: str,
    user_id: str = Query(min_length=1, max_length=128),
    db: Session = Depends(get_db),
) -> None:
    index = get_index()
    skill = index.get(skill_id)
    if skill is None:
        raise HTTPException(status_code=404, detail="Skill not found.")
    if skill.source != "user":
        raise HTTPException(
            status_code=409,
            detail="Skills that ship with Pentagon cannot be deleted.",
        )
    if db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found.")
    try:
        skill.path.unlink()
        skill.path.parent.rmdir()
    except OSError:
        raise HTTPException(
            status_code=500, detail="Could not delete the skill file."
        ) from None
    index.refresh()
    # A deleted skill's toggle row would silently re-apply if it ever returned.
    row = db.get(SkillSetting, {"user_id": user_id, "skill_id": skill_id})
    if row is not None:
        db.delete(row)
        db.commit()
