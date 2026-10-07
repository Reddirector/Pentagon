"""Skill packs: capability instructions that load only when they matter.

A skill is a folder with a ``SKILL.md`` manifest — YAML frontmatter
(``name``, ``description``, ``triggers``, ``risk_category``,
``requires_tools``) over a body of instructions — plus any helper files it
wants to reference. The same three-part shape as a deferred-tool search:
this index keeps only the **frontmatter** in memory (cheap, always there),
``search_skills`` scores that light index against a query, and the body is
read from disk only for the few skills that actually matched, for this turn
only. Pulling every body into context on every turn is exactly the system
prompt bloat the skills system exists to avoid.

Two roots are scanned: ``skills/public`` (shipped with Pentagon) and
``skills/user`` (created from Settings → Skills). Both are re-scanned on
access — file stamps decide what to reparse — so dropping a new
``SKILL.md`` into ``skills/user/`` takes effect on the next turn with no
restart. A malformed manifest is skipped with a warning and never crashes
the scan: a user's typo must not take the app's instructions down.

``risk_category`` reuses the permission system's tier enum
(``app.agent.schemas.Tier``): ``read``, ``write``, ``destructive``,
``external_send`` — the same words the approval ladder already reasons
about, so a skill that assumes risky capability is flagged with the
vocabulary the gates use.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any, get_args

import yaml

from app.agent.schemas import Tier

logger = logging.getLogger(__name__)

# Shipped skills live next to the backend package (not relative to the
# process cwd): the app, its tests and its scripts all find the same files.
DEFAULT_SKILLS_DIR = Path(__file__).resolve().parents[2] / "skills"

RISK_CATEGORIES: frozenset[str] = frozenset(get_args(Tier))
DESCRIPTION_MAX_CHARS = 200
# A whole turn must not become a wall of skill text: at most this many
# bodies load per turn, best score first (RAG-era budget discipline).
MAX_SKILLS_PER_TURN = 3
# One trigger phrase hit, or three content-word overlaps with the
# description, is enough to consider a skill relevant.
SCORE_THRESHOLD = 3

_WORD = re.compile(r"\w+", re.UNICODE)


def _normalize_word(word: str) -> str:
    """Lightest possible stemmer: one trailing plural "s", nothing else.

    Queries say "citations" and "reports"; triggers are written singular.
    "ss"/"us"/"is" endings are left alone ("status" must not become
    "statu") — this is a relevance nudge, not a linguist.
    """
    word = word.lower()
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word

# Words too generic to mean a skill is wanted ("the request" would light up
# half the library). Content words only, and only reasonably long ones.
_STOPWORDS = frozenset(
    """
    the a an and or of to in for on with is are was were be been being this
    that these those what when where which how why who whom whose do does did
    done can could should would will shall may might must you your yours i my
    me mine we our us our as at by from not no yes if then than but about
    into over under after before there here their its it he she they them
    please thanks thank want needs need like just also very much more most
    other another some any all each both per via using use used make makes
    made get gets got give gives given tell says say said one two three
    """.split()
)


class SkillFormatError(ValueError):
    """A manifest that cannot be trusted to describe its own skill."""


@dataclass(frozen=True)
class Skill:
    """Frontmatter only — the cheap half that is always indexed."""

    skill_id: str
    name: str
    description: str
    triggers: tuple[str, ...]
    risk_category: str
    requires_tools: tuple[str, ...]
    source: str  # "public" | "user"
    path: Path

    def as_dict(self) -> dict[str, object]:
        return {
            "id": self.skill_id,
            "name": self.name,
            "description": self.description,
            "triggers": list(self.triggers),
            "risk_category": self.risk_category,
            "requires_tools": list(self.requires_tools),
            "source": self.source,
        }


@dataclass(frozen=True)
class SkillMatch:
    skill: Skill
    score: int


def parse_frontmatter(text: str, origin: str) -> tuple[dict[str, Any], str]:
    """Split a SKILL.md into (frontmatter dict, body). Raises SkillFormatError."""
    lines = text.splitlines(keepends=True)
    if not lines or lines[0].strip() != "---":
        raise SkillFormatError(f"{origin}: must open with a `---` frontmatter block")
    closing = None
    for index in range(1, len(lines)):
        if lines[index].strip() == "---":
            closing = index
            break
    if closing is None:
        raise SkillFormatError(f"{origin}: frontmatter block is never closed with `---`")
    try:
        meta = yaml.safe_load("".join(lines[1:closing])) or {}
    except yaml.YAMLError as exc:
        raise SkillFormatError(f"{origin}: frontmatter is not valid YAML ({exc})") from None
    if not isinstance(meta, dict):
        raise SkillFormatError(f"{origin}: frontmatter must be a mapping of fields")
    body = "".join(lines[closing + 1 :]).strip("\n")
    return meta, body


def build_manifest(
    *,
    name: str,
    description: str,
    triggers: list[str],
    risk_category: str,
    requires_tools: list[str],
) -> str:
    """Frontmatter for a new skill file — one place that knows the field order."""
    meta: dict[str, Any] = {
        "name": name.strip(),
        "description": " ".join(description.split()),
        "triggers": [t.strip() for t in triggers if t.strip()],
        "risk_category": risk_category,
    }
    if requires_tools:
        meta["requires_tools"] = [t.strip() for t in requires_tools if t.strip()]
    return yaml.safe_dump(meta, sort_keys=False, allow_unicode=True, width=100)


def _normalize(
    skill_id: str,
    meta: dict[str, Any],
    source: str,
    path: Path,
) -> Skill:
    name = str(meta.get("name") or "").strip()
    description = " ".join(str(meta.get("description") or "").split())
    if not name:
        raise SkillFormatError(f"{path}: frontmatter needs a `name`")
    if not description:
        raise SkillFormatError(f"{path}: frontmatter needs a `description`")
    triggers = tuple(
        str(item).strip().lower()
        for item in (meta.get("triggers") or [])
        if str(item).strip()
    )
    raw_risk = str(meta.get("risk_category") or "read").strip()
    if raw_risk not in RISK_CATEGORIES:
        # Not guessable: an unclassified skill is one whose risk nobody can
        # see, so it is refused rather than assumed safe.
        raise SkillFormatError(
            f"{path}: risk_category {raw_risk!r} is not one of "
            f"{sorted(RISK_CATEGORIES)}"
        )
    requires_tools = tuple(
        str(item).strip()
        for item in (meta.get("requires_tools") or [])
        if str(item).strip()
    )
    return Skill(
        skill_id=skill_id,
        name=name,
        description=description,
        triggers=triggers,
        risk_category=raw_risk,
        requires_tools=requires_tools,
        source=source,
        path=path,
    )


def tokenize(text: str) -> set[str]:
    return {_normalize_word(word) for word in _WORD.findall(text.lower())}


def _phrase_tokens(phrase: str) -> set[str]:
    """Content words of a trigger phrase. Stopwords and 1-2 letter tokens
    drop out so "write a report" matches a query that omits the "a"."""
    return {
        _normalize_word(word)
        for word in _WORD.findall(phrase.lower())
        if word not in _STOPWORDS and len(word) >= 3
    }


def score_skill(skill: Skill, query_tokens: set[str]) -> int:
    """How relevant this skill is to the query. Deterministic, local, free.

    A trigger is written to be *the* phrase a user would say ("research
    report", "spreadsheet"), so one hit clears the bar on its own: a single
    word must appear as a token, a phrase needs all of its content words
    (order-free, so "write me a report" still fires "write a report"). Plain
    description overlap has to reach three content words, which keeps generic
    vocabulary from loading skills nobody asked for.
    """
    score = 0
    for trigger in skill.triggers:
        words = _WORD.findall(trigger.lower())
        if not words:
            continue
        target = _phrase_tokens(trigger)
        if not target:
            continue
        if len(words) == 1:
            if _normalize_word(words[0]) in query_tokens:
                score += 3
        elif target <= query_tokens:
            # A phrase whose other words were all stop/short words ("write
            # it up" -> {write}) is worth less than a real multi-word hit:
            # on its own it must not be enough to load the skill, or every
            # message containing "write" would load the writing pack.
            score += 3 if len(target) >= 2 else 2
    description_tokens = {
        word
        for word in tokenize(f"{skill.name} {skill.description}")
        if word not in _STOPWORDS and len(word) >= 4
    }
    for word in description_tokens & query_tokens:
        score += 1
    return score


class SkillsIndex:
    """Frontmatter index over one skills root, refreshed on access."""

    def __init__(self, root: Path | str | None = None) -> None:
        self.root = Path(root) if root is not None else DEFAULT_SKILLS_DIR
        self._skills: dict[str, Skill] = {}
        # path -> (mtime_ns, size): the cheap "did this file change?" stamp.
        self._stamps: dict[Path, tuple[int, int]] = {}

    # -- scanning -----------------------------------------------------------
    def _discover(self) -> dict[Path, tuple[int, int]]:
        found: dict[Path, tuple[int, int]] = {}
        for source in ("public", "user"):
            directory = self.root / source
            if not directory.is_dir():
                continue
            try:
                candidates = sorted(directory.glob("*/SKILL.md"))
            except OSError:  # pragma: no cover - unreadable directory
                continue
            for path in candidates:
                try:
                    stat = path.stat()
                except OSError:  # pragma: no cover - vanished mid-scan
                    continue
                found[path] = (stat.st_mtime_ns, stat.st_size)
        return found

    @staticmethod
    def _source_of(path: Path) -> str:
        return "public" if path.parent.parent.name == "public" else "user"

    def _forget(self, path: Path) -> None:
        self._stamps.pop(path, None)
        for skill_id, skill in list(self._skills.items()):
            if skill.path == path:
                del self._skills[skill_id]

    def refresh(self) -> None:
        """Pick up added, edited and removed skill files.

        Only files whose stamp changed are reparsed; the whole directory walk
        is two globs and a stat per file, cheap enough to run before every
        search, which is what makes "no restart needed" true rather than
        aspirational.
        """
        found = self._discover()
        for path in list(self._stamps):
            if path not in found:
                self._forget(path)
        for path, stamp in found.items():
            if self._stamps.get(path) == stamp:
                continue
            self._forget(path)
            self._stamps[path] = stamp
            try:
                text = path.read_text(encoding="utf-8")
                meta, _body = parse_frontmatter(text, str(path))
                skill = _normalize(path.parent.name, meta, self._source_of(path), path)
            except (SkillFormatError, OSError, UnicodeDecodeError) as exc:
                logger.warning("skill file ignored: %s", exc)
                continue
            existing = self._skills.get(skill.skill_id)
            if existing is not None:
                logger.warning(
                    "skill id %r (%s) collides with %s; keeping the first",
                    skill.skill_id,
                    path,
                    existing.path,
                )
                continue
            self._skills[skill.skill_id] = skill

    # -- queries ------------------------------------------------------------
    def all(self) -> list[Skill]:
        self.refresh()
        return sorted(self._skills.values(), key=lambda s: (s.source, s.skill_id))

    def get(self, skill_id: str) -> Skill | None:
        self.refresh()
        return self._skills.get(skill_id)

    def body(self, skill_id: str) -> str:
        """Read one skill's instructions — only when someone actually wants them."""
        skill = self._skills.get(skill_id) or self.get(skill_id)
        if skill is None:
            raise KeyError(skill_id)
        text = skill.path.read_text(encoding="utf-8")
        _meta, body = parse_frontmatter(text, str(skill.path))
        if not body:
            raise SkillFormatError(f"{skill.path}: has no instruction body")
        return body

    def search_skills(self, query: str) -> list[SkillMatch]:
        """Score the light index; bodies are NOT read here."""
        self.refresh()
        if not query.strip():
            return []
        query_tokens = tokenize(query)
        matches = [
            SkillMatch(skill=skill, score=score_skill(skill, query_tokens))
            for skill in self._skills.values()
        ]
        relevant = [match for match in matches if match.score >= SCORE_THRESHOLD]
        relevant.sort(key=lambda match: (-match.score, match.skill.skill_id))
        return relevant


_INDEXES: dict[str, SkillsIndex] = {}


def get_index() -> SkillsIndex:
    """The process-wide index for the current skills root (one per root).

    Keyed by root so a test (or a future setting) can point at a different
    directory and get a fresh index instead of a stale cache.
    """
    key = str(DEFAULT_SKILLS_DIR)
    index = _INDEXES.get(key)
    if index is None:
        index = SkillsIndex(DEFAULT_SKILLS_DIR)
        _INDEXES[key] = index
    return index
