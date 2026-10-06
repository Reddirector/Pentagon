"""The capability that proves a caller is the app and not just a guesser.

``user_id`` is a scoping key, not a credential: it turns up in config files and
in screenshots, so anyone holding it could approve a command, read what the
model is about to do, or hand over a location on the user's behalf.

This module adds the missing half. A random token is generated once, stored in
a file only the user can read, and required on the endpoints that authorise
something. Knowing the ``user_id`` stops being enough.

It is deliberately *not* authentication. A caller who can read the user's files
can read the token too, so this does not survive an attacker who already has
filesystem access as that user. It raises the bar from "knows a string that
leaks" to "can read your private files", which is the part that was actually
cheap to get wrong.
"""

from __future__ import annotations

import hmac
import os
import secrets
import stat
import threading
from pathlib import Path

_lock = threading.Lock()
_cached: str | None = None


def token_path() -> Path:
    """Where the secret lives. Overridable so tests never touch the real one."""
    from app.config import settings

    configured = (settings.capability_token_path or "").strip()
    if configured:
        return Path(configured).expanduser()
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base).expanduser() / "pentagon" / "capability-token"


def load_or_create(*, force_new: bool = False) -> str:
    """Read the token, creating it on first use.

    The file is written with 0600 *before* any content is written to it, so it
    is never briefly world-readable.
    """
    global _cached
    with _lock:
        if _cached is not None and not force_new:
            return _cached
        path = token_path()
        if not force_new and path.is_file():
            try:
                existing = path.read_text(encoding="utf-8").strip()
            except OSError:
                existing = ""
            if existing:
                _tighten(path)
                _cached = existing
                return existing
        token = secrets.token_urlsafe(32)
        try:
            path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            # Create empty with restrictive permissions, then fill it.
            handle = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
            try:
                os.write(handle, token.encode("utf-8"))
            finally:
                os.close(handle)
        except OSError:
            # A read-only home should not stop the app from starting; the token
            # simply lives for this process only.
            _cached = token
            return token
        _tighten(path)
        _cached = token
        return token


def _tighten(path: Path) -> None:
    try:
        os.chmod(path, stat.S_IRUSR | stat.S_IWUSR)
    except OSError:
        pass


def reset_cache() -> None:
    """Forget the in-process copy. Used by tests and after rotation."""
    global _cached
    with _lock:
        _cached = None


def verify(candidate: str | None) -> bool:
    """Constant-time comparison, so a wrong token leaks nothing by timing."""
    if not candidate:
        return False
    expected = load_or_create()
    return hmac.compare_digest(candidate, expected)