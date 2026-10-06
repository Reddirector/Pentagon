"""Per-turn tracing: what the model called, what came back, how long it took.

Rows land in the ``tool_traces`` table. Arguments are redacted before they are
stored -- secret-shaped keys are masked and long values cut -- because traces
are diagnostics, not a second transcript, and must never become the place a
credential leaks.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.db.models import ToolTrace
from app.db.session import SessionLocal

logger = logging.getLogger(__name__)

_SECRET_KEY = re.compile(
    r"key|token|secret|password|authorization|credential", re.IGNORECASE
)
_MAX_VALUE_CHARS = 200


def redact_args(args: dict[str, Any]) -> dict[str, Any]:
    """A copy of ``args`` safe to persist: secret-shaped keys masked, long strings cut."""
    redacted: dict[str, Any] = {}
    for key, value in args.items():
        if _SECRET_KEY.search(str(key)):
            redacted[key] = "[redacted]"
        elif isinstance(value, str) and len(value) > _MAX_VALUE_CHARS:
            redacted[key] = value[:_MAX_VALUE_CHARS] + f"... [{len(value)} chars total]"
        else:
            redacted[key] = value
    return redacted


class TraceRecorder:
    """Collects one turn's tool calls and flushes them as ``tool_traces`` rows."""

    def __init__(self, user_id: str, conversation_id: str, turn_id: str) -> None:
        self.user_id = user_id
        self.conversation_id = conversation_id
        self.turn_id = turn_id
        self._rows: list[dict[str, Any]] = []

    def record_tool_call(
        self,
        step: int,
        tool: str,
        args: dict[str, Any],
        status: str,
        *,
        duration_ms: float | None = None,
        tokens_in: int | None = None,
        tokens_out: int | None = None,
    ) -> None:
        """Buffer one tool call. ``status``: ok | error | denied | cached | timeout."""
        self._rows.append(
            {
                "user_id": self.user_id,
                "conversation_id": self.conversation_id,
                "turn_id": self.turn_id,
                "step": step,
                "tool": tool,
                "args_redacted": redact_args(args),
                "status": status,
                "duration_ms": round(duration_ms) if duration_ms is not None else None,
                "tokens_in": tokens_in,
                "tokens_out": tokens_out,
            }
        )

    def flush(self) -> int:
        """Insert the buffered rows; returns how many were written.

        Tracing is diagnostic and must never break the turn it observes, so a
        database failure is logged and the buffer is kept for a later retry
        rather than raised into the agent loop.
        """
        if not self._rows:
            return 0
        try:
            with SessionLocal() as db:
                for row in self._rows:
                    db.add(ToolTrace(**row))
                db.commit()
        except Exception:
            logger.warning(
                "tool trace flush failed (%d rows kept in memory)",
                len(self._rows),
                exc_info=True,
            )
            return 0
        written = len(self._rows)
        self._rows.clear()
        return written
