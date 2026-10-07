"""Skill packs: loader, matcher, and the API behind Settings → Skills.

The loader's contract is what makes §5's "no restart" real: frontmatter
only in memory, file stamps for change detection, bodies read on demand.
The matcher's contract is the deferred-detail principle itself — cheap
listing always there, full instructions only for what matched, never for
what did not.
"""

from __future__ import annotations

import logging
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from app.db.models import User
from app.db.session import SessionLocal
from app.main import app
from app.skills import loader as loader_module
from app.skills.loader import (
    DESCRIPTION_MAX_CHARS,
    MAX_SKILLS_PER_TURN,
    RISK_CATEGORIES,
    SkillFormatError,
    SkillsIndex,
    parse_frontmatter,
)
from app.skills.router import match_for_turn


@pytest.fixture
def client() -> TestClient:
    return TestClient(app)


@pytest.fixture
def user_id() -> str:
    uid = f"skills-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=uid))
        db.commit()
    return uid


@pytest.fixture
def root(tmp_path, monkeypatch):
    """A private skills root: empty public/user dirs, no shipped skills."""
    (tmp_path / "public").mkdir()
    (tmp_path / "user").mkdir()
    monkeypatch.setattr(loader_module, "DEFAULT_SKILLS_DIR", tmp_path)
    return tmp_path


def write_skill(
    root,
    skill_id: str,
    *,
    source: str = "user",
    name: str | None = None,
    description: str = "A skill description specific enough to trigger on purpose.",
    triggers: list[str] | None = None,
    risk_category: str = "read",
    requires_tools: list[str] | None = None,
    body: str = "Do the thing carefully, step by step. Check your work.",
    raw: str | None = None,
):
    directory = root / source / skill_id
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "SKILL.md"
    if raw is not None:
        path.write_text(raw, encoding="utf-8")
        return path
    lines = [
        "---",
        f"name: {name or skill_id}",
        f"description: {description}",
        f"triggers: [{', '.join(triggers or [skill_id])}]",
        f"risk_category: {risk_category}",
    ]
    if requires_tools:
        lines.append(f"requires_tools: [{', '.join(requires_tools)}]")
    lines += ["---", "", body, ""]
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


# --- shipped skills ---------------------------------------------------------
def test_shipped_skills_are_real_and_well_formed() -> None:
    """The five public skills must parse, fit their caps, and have bodies —
    a stub shipped as a skill is a skill that silently loads nothing."""
    index = SkillsIndex(loader_module.DEFAULT_SKILLS_DIR)
    skills = [skill for skill in index.all() if skill.source == "public"]
    ids = {skill.skill_id for skill in skills}
    assert ids == {
        "document-writing",
        "web-research",
        "code-generation",
        "data-analysis",
        "citation-and-sourcing",
    }
    for skill in skills:
        assert 0 < len(skill.description) <= DESCRIPTION_MAX_CHARS, skill.skill_id
        assert skill.triggers, f"{skill.skill_id} has no triggers"
        assert skill.risk_category in RISK_CATEGORIES
        body = index.body(skill.skill_id)
        assert len(body) > 500, f"{skill.skill_id} body is a stub ({len(body)} chars)"
        # Structure the prompt's format promises: a level-1 heading body.
        assert body.lstrip().startswith("# ")


def test_shipped_skills_need_tools_that_exist() -> None:
    """Shipped requires_tools must reference real tool names, or every turn
    would carry a missing-capability note for skills Pentagon wrote itself."""
    from app.agent.bootstrap import build_registry

    registered = set(build_registry().names())
    index = SkillsIndex(loader_module.DEFAULT_SKILLS_DIR)
    for skill in index.all():
        unknown = [tool for tool in skill.requires_tools if tool not in registered]
        assert not unknown, f"{skill.skill_id} assumes unregistered {unknown}"


# --- loader mechanics -------------------------------------------------------
def test_frontmatter_round_trip() -> None:
    text = "---\nname: x\ndescription: 'One line.'\ntriggers: [a, b]\nrisk_category: read\n---\n\nBody here.\n"
    meta, body = parse_frontmatter(text, "test")
    assert meta["name"] == "x"
    assert meta["triggers"] == ["a", "b"]
    assert body == "Body here."


def test_malformed_skill_is_skipped_not_fatal(root) -> None:
    write_skill(root, "good", triggers=["goodskill"], body="A real body of some length.")
    write_skill(
        root,
        "broken",
        raw="no frontmatter here at all",
    )
    write_skill(
        root,
        "bad-risk",
        raw="---\nname: bad\ndescription: desc\nrisk_category: everything_fine\n---\nbody",
    )

    index = SkillsIndex(root)
    with pytest.raises(KeyError):
        index.body("broken")  # never indexed -> there is no body to read
    with pytest.raises(SkillFormatError):
        parse_frontmatter("no frontmatter here at all", "test")
    ids = {skill.skill_id for skill in index.all()}
    assert ids == {"good"}, f"a broken file must not appear, got {ids}"
    # The good skill still loads and searches despite its broken neighbour.
    assert [m.skill.skill_id for m in index.search_skills("goodskill")] == ["good"]


def test_hot_reload_picks_up_edits_without_a_restart(root, caplog) -> None:
    """Acceptance §6.1: a new SKILL.md under skills/user/ is live immediately."""
    index = SkillsIndex(root)
    assert index.all() == []

    write_skill(
        root,
        "late-arrival",
        triggers=["zebrafish"],
        description="Everything about zebrafish tanks and their maintenance routines.",
        body="ZEBRAFISH BODY marker",
    )
    found = index.search_skills("zebrafish")
    assert [m.skill.skill_id for m in found] == ["late-arrival"], (
        "a new file must be found without constructing a new index"
    )
    assert "ZEBRAFISH BODY marker" in index.body("late-arrival")

    # Editing the description re-scores; editing the body is read live.
    write_skill(
        root,
        "late-arrival",
        triggers=["zebrafish"],
        description="Everything about axolotl tanks and their maintenance routines.",
        body="AXOLOTL BODY marker",
    )
    assert index.body("late-arrival") == "AXOLOTL BODY marker"
    # The trigger no longer matches, but the edited description does: three
    # content words is what the description-overlap path requires.
    assert index.search_skills("axolotl tanks maintenance"), (
        "the edited description must be re-indexed"
    )

    # Deleting it takes it back out.
    (root / "user" / "late-arrival" / "SKILL.md").unlink()
    assert index.get("late-arrival") is None
    assert index.search_skills("zebrafish") == []


def test_bodies_load_only_for_matches(root) -> None:
    """The deferred-detail principle: search reads frontmatter, not bodies."""
    write_skill(root, "alpha", triggers=["apples"], body="ALPHA BODY")
    write_skill(root, "beta", triggers=["bananas"], body="BETA BODY")
    index = SkillsIndex(root)

    matches = index.search_skills("apples please")
    assert [m.skill.skill_id for m in matches] == ["alpha"]
    # The match object carries frontmatter only — the body was never read.
    assert "ALPHA BODY" not in repr(matches[0])
    assert index.body("alpha") == "ALPHA BODY"


def test_matching_zero_one_and_many(root) -> None:
    write_skill(root, "alpha", triggers=["apples"], description="All about apples and orchards.", body="ALPHA BODY")
    write_skill(root, "beta", triggers=["bananas"], description="All about bananas and smoothies.", body="BETA BODY")
    write_skill(root, "gamma", triggers=["oranges"], description="All about oranges and marmalade.", body="GAMMA BODY")
    index = SkillsIndex(root)

    assert index.search_skills("what is the capital of France") == []
    assert [m.skill.skill_id for m in index.search_skills("apples")] == ["alpha"]
    many = index.search_skills("apples and bananas with oranges")
    assert {m.skill.skill_id for m in many} == {"alpha", "beta", "gamma"}


def test_turn_cap_is_three(root) -> None:
    for n in range(MAX_SKILLS_PER_TURN + 2):
        write_skill(
            root,
            f"pack-{n}",
            triggers=[f"unicorntopic{n}"],
            description=f"Skill number {n} about unicorntopic{n} matters.",
            body=f"PACK {n} BODY",
        )
    index = SkillsIndex(root)
    query = " ".join(f"unicorntopic{n}" for n in range(MAX_SKILLS_PER_TURN + 2))
    matches = index.search_skills(query)
    assert len(matches) == MAX_SKILLS_PER_TURN + 2, "all five should be relevant"
    result = match_for_turn(user_id="", user_message=query, history=[])
    assert len(result.fired) == MAX_SKILLS_PER_TURN, (
        "the per-turn cap must stop an overeager matcher from flooding context"
    )


def test_disabled_skill_is_excluded_from_matching(root, user_id) -> None:
    write_skill(root, "alpha", triggers=["apples"], body="ALPHA BODY")
    assert match_for_turn(user_id=user_id, user_message="apples", history=()).fired == (
        "alpha",
    ), "sanity: it matches while enabled"
    with SessionLocal() as db:
        from app.db.models import SkillSetting

        db.add(SkillSetting(user_id=user_id, skill_id="alpha", enabled=False))
        db.commit()

    result = match_for_turn(user_id=user_id, user_message="apples", history=())
    assert result.fired == (), "off must mean excluded from the router, not deprioritised"
    assert result.instructions == ""


def test_empty_match_logs_an_empty_fired_list(root, caplog) -> None:
    """Acceptance §6.2: verifiable through the per-turn log."""
    with caplog.at_level(logging.INFO, logger="app.skills.router"):
        result = match_for_turn(user_id="", user_message="unrelated question entirely", history=())
    assert result.fired == ()
    messages = [record.getMessage() for record in caplog.records]
    assert any("skills fired: []" in message for message in messages), messages


def test_history_participates_in_matching(root) -> None:
    """A follow-up pronoun still counts: matching sees recent context."""
    from langchain_core.messages import HumanMessage

    write_skill(root, "alpha", triggers=["apples"], body="ALPHA BODY")
    index = SkillsIndex(root)
    matches = index.search_skills(
        "tell me about the harvest\napples are the topic we started with"
    )
    assert [m.skill.skill_id for m in matches] == ["alpha"]
    result = match_for_turn(
        user_id="",
        user_message="and now compare them",
        history=[HumanMessage(content="Tell me about apples and the harvest")],
    )
    assert result.fired == ("alpha",), result


def test_missing_tool_note_precedes_the_body(root) -> None:
    write_skill(
        root,
        "needs-ghost",
        triggers=["ghosttopic"],
        requires_tools=["definitely_not_a_tool"],
        body="GHOST BODY INSTRUCTIONS",
    )
    result = match_for_turn(user_id="", user_message="ghosttopic please", history=())
    assert result.fired == ("needs-ghost",)
    note_at = result.instructions.find("not available")
    body_at = result.instructions.find("GHOST BODY INSTRUCTIONS")
    assert note_at != -1, "a missing capability must be flagged, not hidden"
    assert "definitely_not_a_tool" in result.instructions
    assert 0 < note_at < body_at, "the note must be prepended, not appended"


def test_known_tools_produce_no_note(root) -> None:
    write_skill(
        root,
        "needs-search",
        triggers=["searchtopic"],
        requires_tools=["web_search"],
        body="SEARCH BODY INSTRUCTIONS",
    )
    result = match_for_turn(user_id="", user_message="searchtopic please", history=())
    assert result.fired == ("needs-search",)
    assert "not available" not in result.instructions


# --- API --------------------------------------------------------------------
def test_list_includes_public_and_user_skills(client: TestClient, user_id: str, root) -> None:
    write_skill(root, "theirs", source="public", triggers=["theirs"], description="Shipped skill.")
    write_skill(root, "mine", source="user", triggers=["mine"], description="User skill.")
    rows = {row["id"]: row for row in client.get(f"/api/skills?user_id={user_id}").json()}
    assert rows["theirs"]["source"] == "public"
    assert rows["mine"]["source"] == "user"
    assert rows["theirs"]["enabled"] is True
    assert rows["mine"]["enabled"] is True


def test_create_skill_writes_a_valid_manifest(client: TestClient, user_id: str, root) -> None:
    response = client.post(
        "/api/skills",
        json={
            "user_id": user_id,
            "name": "My Fishing Notes",
            "description": "How to log and recall freshwater fishing notes. Use for fishing records.",
            "triggers": ["fishing", "catch log"],
            "risk_category": "read",
            "requires_tools": ["recall"],
            "body": "Record the lake, the date, and the lure. Nothing else matters.",
        },
    )
    assert response.status_code == 201, response.text
    created = response.json()
    assert created["id"] == "my-fishing-notes"
    assert created["enabled"] is True
    assert created["source"] == "user"

    path = root / "user" / "my-fishing-notes" / "SKILL.md"
    assert path.is_file()
    meta, body = parse_frontmatter(path.read_text(encoding="utf-8"), str(path))
    assert meta["name"] == "My Fishing Notes"
    assert meta["triggers"] == ["fishing", "catch log"]
    assert meta["risk_category"] == "read"
    assert meta["requires_tools"] == ["recall"]
    assert "Record the lake" in body
    # And it matches right away — no restart, no re-scan call.
    result = match_for_turn(user_id=user_id, user_message="fishing log please", history=())
    assert result.fired == ("my-fishing-notes",)


@pytest.mark.parametrize(
    ("payload_overrides", "expected_detail"),
    [
        ({"description": "x" * (DESCRIPTION_MAX_CHARS + 1)}, "capped at"),
        ({"triggers": []}, "trigger"),
        ({"risk_category": "mind_control"}, "permission system"),
        ({"body": "   "}, "body"),
        ({"name": "--- !!"}, "letters or digits"),
    ],
)
def test_create_skill_validation(
    client: TestClient, user_id: str, root, payload_overrides, expected_detail
) -> None:
    payload = {
        "user_id": user_id,
        "name": "Valid name",
        "description": "A perfectly reasonable description of the skill's job.",
        "triggers": ["triggerword"],
        "risk_category": "read",
        "body": "A real instruction body.",
    }
    payload.update(payload_overrides)
    response = client.post("/api/skills", json=payload)
    assert response.status_code == 422, response.text
    assert expected_detail in response.json()["detail"], response.json()["detail"]
    assert list((root / "user").glob("*/SKILL.md")) == [], "a rejected skill writes nothing"


def test_duplicate_skill_name_conflicts(client: TestClient, user_id: str, root) -> None:
    payload = {
        "user_id": user_id,
        "name": "Twin Skill",
        "description": "A perfectly reasonable description of the skill's job.",
        "triggers": ["distinct"],
        "risk_category": "read",
        "body": "Body.",
    }
    assert client.post("/api/skills", json=payload).status_code == 201
    payload["name"] = "twin!skill"  # same slug, different spelling
    conflict = client.post("/api/skills", json=payload)
    assert conflict.status_code == 409, conflict.text


def test_toggle_round_trip_and_public_delete_refusal(
    client: TestClient, user_id: str, root
) -> None:
    write_skill(root, "mine", triggers=["mine"], description="Mine only.", body="B")
    write_skill(root, "theirs", source="public", triggers=["theirs"], body="B")

    disabled = client.patch(
        "/api/skills/mine", json={"user_id": user_id, "enabled": False}
    )
    assert disabled.status_code == 200
    assert disabled.json()["enabled"] is False
    rows = {row["id"]: row for row in client.get(f"/api/skills?user_id={user_id}").json()}
    assert rows["mine"]["enabled"] is False

    # Re-enabling stores the truth rather than only deleting rows lazily.
    enabled = client.patch(
        "/api/skills/mine", json={"user_id": user_id, "enabled": True}
    )
    assert enabled.json()["enabled"] is True
    rows = {row["id"]: row for row in client.get(f"/api/skills?user_id={user_id}").json()}
    assert rows["mine"]["enabled"] is True

    # Toggling a skill that does not exist is a 404, not a silent write.
    assert (
        client.patch("/api/skills/ghost", json={"user_id": user_id, "enabled": False}).status_code
        == 404
    )
    # Shipped skills cannot be deleted.
    assert client.delete(f"/api/skills/theirs?user_id={user_id}").status_code == 409
    # A user's own can.
    assert client.delete(f"/api/skills/mine?user_id={user_id}").status_code == 204
    remaining = {row["id"] for row in client.get(f"/api/skills?user_id={user_id}").json()}
    assert remaining == {"theirs"}, "only the user's own skill should disappear"


def test_foreign_user_cannot_see_or_flip_a_toggle(
    client: TestClient, user_id: str, root
) -> None:
    intruder = f"intruder-{uuid4()}"
    with SessionLocal() as db:
        db.add(User(id=intruder))
        db.commit()
    write_skill(root, "mine", triggers=["mine"], body="B")
    client.patch("/api/skills/mine", json={"user_id": user_id, "enabled": False})

    # The skill list itself is per-user state: intruder sees their own (on).
    rows = {row["id"]: row for row in client.get(f"/api/skills?user_id={intruder}").json()}
    assert rows["mine"]["enabled"] is True, "one user's toggle must not apply to another"
    # And a toggle for an unknown user is refused.
    assert (
        client.patch(
            "/api/skills/mine", json={"user_id": f"ghost-{uuid4()}", "enabled": False}
        ).status_code
        == 404
    )
