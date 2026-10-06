"""`.env.example` must not drift from the settings it documents.

Two failures are easy to commit here, and both are the same shape: a setting
that silently does nothing.

* A documented variable that no longer exists. Someone sets it, expects it to
  work, and gets silence.
* A real setting with no documentation. It defaults, so nobody notices it was
  never offered as a knob.

This test compares both directions, so either mistake fails the suite instead of
waiting to be found in production.
"""

from __future__ import annotations

import re
from pathlib import Path

from app.config import Settings

ENV_EXAMPLE = Path(__file__).resolve().parents[1] / ".env.example"

# Secrets a deployment must supply and that are therefore not defaulted in the
# example file; they are documented elsewhere.
_ALLOWED_ABSENT = frozenset()


def _documented() -> set[str]:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    return {
        match
        for match in re.findall(r"^([A-Z][A-Z0-9_]+)=", text, flags=re.MULTILINE)
    }


def _real() -> set[str]:
    return {name.upper() for name in Settings.model_fields}


def test_env_example_exists():
    assert ENV_EXAMPLE.is_file(), f"{ENV_EXAMPLE} is missing"


def test_no_documented_variable_is_ignored_by_the_settings():
    """The worst failure: documented, set by the user, silently inert."""
    stale = sorted(_documented() - _real() - _ALLOWED_ABSENT)
    assert not stale, (
        "documented in .env.example but not a real setting, so setting them does "
        f"nothing: {stale}"
    )


def test_every_setting_is_documented():
    """A setting nobody was told about is a knob nobody will turn."""
    undocumented = sorted(_real() - _documented() - _ALLOWED_ABSENT)
    assert not undocumented, f"real settings missing from .env.example: {undocumented}"


def test_the_removed_desktop_action_timeout_stays_removed():
    """A regression guard for a setting that was deleted during cleanup."""
    assert "desktop_action_timeout_seconds" not in Settings.model_fields
    assert "DESKTOP_ACTION_TIMEOUT_SECONDS" not in _documented()


def test_defaults_in_the_example_match_the_real_defaults():
    """A wrong default in the docs is as misleading as a missing one.

    Numbers are compared as numbers: ``300`` is the same value as the float
    default ``300.0``, and writing it that way is clearer in a config file.
    """
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    mismatched: list[str] = []
    for name, field in Settings.model_fields.items():
        env_name = name.upper()
        match = re.search(rf"^{env_name}=(.*)$", text, flags=re.MULTILINE)
        if not match:
            continue
        documented = match.group(1).strip()
        default = field.default
        if isinstance(default, bool):
            if documented not in ("true", "false", ""):
                mismatched.append(f"{env_name}: docs={documented!r} default={default!r}")
            continue
        if default is None or isinstance(default, str):
            # Secrets are blank in the example; empty strings pass through.
            if documented and isinstance(default, str) and documented != default:
                mismatched.append(f"{env_name}: docs={documented!r} default={default!r}")
            continue
        try:
            same = float(documented) == float(default)
        except ValueError:
            same = documented == str(default)
        if not same:
            mismatched.append(f"{env_name}: docs={documented!r} default={default!r}")
    assert not mismatched, "defaults do not match the settings:\n  " + "\n  ".join(mismatched)