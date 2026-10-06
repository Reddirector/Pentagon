"""How much the model may do without stopping to ask.

There is exactly one ladder here, with three rungs, and it is consulted by both
approval gates (the shell runner and the desktop actions) so the two can never
drift apart. The client renders the same three numbers from
``/api/commands/settings``; nothing about the wording lives in two places.

The shape of the ladder, from the ground up:

1. **Restricted** -- everything asks, including commands that only read. Useful
   when you want to see every single thing the model touches.
2. **Balanced** -- anything that changes state asks first; provably read-only
   commands run on their own. This is the default and is what Pentagon did
   before levels existed.
3. **Trusted** -- changes run on their own, but genuinely destructive things
   still ask. "Trusted" is never "unlimited": ``rm -rf`` and ``reboot`` keep
   stopping, because the cost of being wrong there is losing work or losing the
   machine, not just an unwanted side effect.

``FORBIDDEN`` commands and ``_FORBIDDEN`` shell escapes are unaffected by any
level -- they are refused outright, with or without approval. A permission level
lowers how often we interrupt; it never widens what is reachable.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# The level a user gets before they choose one, and the level an existing row
# is assumed to hold once the column exists. Balanced is today's behaviour, so
# upgrading must not silently loosen anyone's posture.
DEFAULT_PERMISSION_LEVEL = 2

MIN_PERMISSION_LEVEL = 1
MAX_PERMISSION_LEVEL = 3


@dataclass(frozen=True)
class PermissionLevel:
    number: int
    name: str
    summary: str
    detail: str

    def as_dict(self) -> dict[str, object]:
        return {
            "level": self.number,
            "name": self.name,
            "summary": self.summary,
            "detail": self.detail,
        }


PERMISSION_LEVELS: dict[int, PermissionLevel] = {
    1: PermissionLevel(
        number=1,
        name="Restricted",
        summary="Ask me before anything runs",
        detail=(
            "Every command and every desktop action stops for your approval, "
            "including ones that only read. The most interruptions, and the "
            "clearest picture of what the model is doing."
        ),
    ),
    2: PermissionLevel(
        number=2,
        name="Balanced",
        summary="Read freely, ask before changing",
        detail=(
            "Commands that only read -- listing files, searching text, checking "
            "status -- run on their own. Anything that changes your system, "
            "opens an application, or controls the desktop asks first."
        ),
    ),
    3: PermissionLevel(
        number=3,
        name="Trusted",
        summary="Run freely, ask before destroying",
        detail=(
            "Actions run on their own. Irreversible things still stop for you: "
            "deleting files, shutting down or restarting the machine, and "
            "commands that could wipe a disk."
        ),
    ),
}


def normalize_level(value: object) -> int:
    """Coerce anything to a usable level, defaulting to the safe middle rung.

    Values arrive from JSON, the database, and hand-written requests. Anything
    out of range, non-integer, or missing falls back to
    ``DEFAULT_PERMISSION_LEVEL`` rather than raising, because a bad row must not
    be able to stop the app from starting or hand out more access than asked
    for.
    """
    try:
        level = int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return DEFAULT_PERMISSION_LEVEL
    if level < MIN_PERMISSION_LEVEL or level > MAX_PERMISSION_LEVEL:
        return DEFAULT_PERMISSION_LEVEL
    return level


def level_info(level: object) -> PermissionLevel:
    """The description of a level, for the API and the client."""
    return PERMISSION_LEVELS[normalize_level(level)]


def levels_as_list() -> list[dict[str, object]]:
    """All three levels, lowest first, so the client can render them in order."""
    return [PERMISSION_LEVELS[number].as_dict() for number in sorted(PERMISSION_LEVELS)]


# --------------------------------------------------------------------------
# The one decision both gates share.
# --------------------------------------------------------------------------


def requires_approval(
    *,
    changes_state: bool,
    level: object,
    destructive: bool = False,
) -> bool:
    """Whether this action has to stop for the user at ``level``.

    ``changes_state`` is the existing signal the gates already compute: whether
    the action can alter the machine. ``destructive`` marks the small,
    deliberately separate set that stays gated even at Trusted, because the
    failure mode is unrecoverable rather than merely unwanted.
    """
    normalized = normalize_level(level)
    if normalized <= 1:
        # Restricted: no exceptions, not even a read.
        return True
    if normalized == 2:
        # Balanced: the long-standing rule.
        return bool(changes_state)
    # Trusted: only the destructive tail still interrupts.
    return bool(destructive)


def requires_tool_approval(tier: str, level: object) -> bool:
    """Whether an agent tool call at ``tier`` stops for the user at ``level``.

    This is the same ladder the shell runner and the desktop actions use,
    with the tool tier translated onto its two signals:

    - ``read`` changes nothing, so it runs by itself at Balanced and Trusted
      and asks at Restricted like everything else.
    - ``write`` changes state, so it asks through Balanced and runs at Trusted.
    - ``destructive`` and ``external_send`` always ask, at every level:
      "Trusted" is never "unlimited", and data leaving the machine cannot be
      recalled any more than a deleted file can.

    The decision reads only the tier and the level. Nothing from a retrieved
    page, a tool result, or an error message is consulted -- content cannot
    move a call up or down this ladder.
    """
    if tier == "read":
        return requires_approval(changes_state=False, level=level)
    if tier == "write":
        return requires_approval(changes_state=True, level=level)
    # destructive, external_send -- and any future tier -- take the strict path.
    return requires_approval(changes_state=True, level=level, destructive=True)


# --------------------------------------------------------------------------
# Destructive shell commands.
# --------------------------------------------------------------------------

# Matched against the whole command line. These are the commands whose mistake
# costs something the user cannot get back -- a deleted file tree, a wiped
# partition, an unexpected reboot mid-sentence. They ask at Trusted; the
# read-only allowlist already covers everything harmless.
_DESTRUCTIVE_PATTERNS: tuple[re.Pattern[str], ...] = (
    # Recursive delete, especially of an absolute path or $HOME.
    re.compile(r"(^|[;&|]\s*)rm\s+(-[a-zA-Z]*[rR][a-zA-Z]*[fF]|-[a-zA-Z]*[fF][a-zA-Z]*[rR])\b"),
    re.compile(r"(^|[;&|]\s*)rm\s+(-[a-zA-Z]*[rR])\b.*\s(?:-[a-zA-Z]*f|--force)\b"),
    # Wiping or repartitioning a device.
    re.compile(r"(^|[;&|]\s*)mkfs(\.[a-z0-9]+)?\b"),
    re.compile(r"(^|[;&|]\s*)dd\b.*\bof=/dev/"),
    re.compile(r"(^|[;&|]\s*)shred\b"),
    # Filesystem and partition surgery.
    re.compile(r"(^|[;&|]\s*)fdisk\b"),
    re.compile(r"(^|[;&|]\s*)parted\b"),
    re.compile(r"(^|[;&|]\s*)wipefs\b"),
    # Power state.
    re.compile(r"(^|[;&|]\s*)(shutdown|reboot|poweroff|halt)\b"),
    re.compile(r"(^|[;&|]\s*)systemctl\s+(poweroff|reboot|halt|suspend|hibernate)\b"),
    # Git history destruction and force pushes.
    re.compile(r"\bgit\s+push\b.*(--force\b|-f\b)"),
    re.compile(r"\bgit\s+(reset\s+--hard|clean\s+-[a-zA-Z]*f)"),
    # History rewriting.
    re.compile(r"\bhistory\s+-c\b"),
    # The sqlite3 CLI's dot-commands can spawn a shell from inside the
    # interpreter (``.system``, ``.shell``), turning any sqlite3 invocation into
    # arbitrary command execution. A database the model can reach is the
    # machine's own trust store; treating this as a write-and-ask, not as an
    # execution primitive.
    re.compile(r"\bsqlite3\b[^;|&]*\.(system|shell)\b"),
)


def is_destructive_command(command: str) -> bool:
    """True when a shell command should still ask at Trusted.

    This is a floor, not a ceiling. It only ever adds questions; it never
    approves anything. A command it does not recognise is still subject to the
    normal rules, so a miss falls back to the stricter level rather than to
    silence.
    """
    return any(pattern.search(command) for pattern in _DESTRUCTIVE_PATTERNS)