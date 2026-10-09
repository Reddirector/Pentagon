"""get_current_time: the date and time for an IANA timezone, from the host clock.

Every model needs this constantly and none of them know it: the answer to
"what date is it", "how many days until Friday" (combined with calculator for
the subtraction) starts here. No web, no API -- the host's clock and zoneinfo.
"""

from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError
from difflib import get_close_matches
from typing import Any

from app.agent.schemas import ToolContext, ToolResult, ToolSpec


def _available_zones() -> list[str]:
    try:
        from zoneinfo import available_timezones

        return sorted(available_timezones())
    except Exception:  # pragma: no cover - platform without tz database
        return []


TOOL_SPEC = ToolSpec(
    name="get_current_time",
    description=(
        "Get the current date and time for an IANA timezone, such as Asia/Kolkata"
        " or Europe/Berlin. Use whenever a question depends on what day or time it"
        " is now, on absolute dates like 'this week' or 'yesterday', or before any"
        " relative-date arithmetic (then compute the difference with calculator)."
        " Do not use it to convert between two timezones the user names -- that"
        " needs only this plus arithmetic. Returns ISO-8601 date, time, weekday,"
        " the UTC offset and the epoch seconds. No network access is involved."
    ),
    parameters={
        "type": "object",
        "properties": {
            "timezone": {
                "type": "string",
                "description": (
                    "An IANA timezone name such as 'UTC', 'Asia/Kolkata' or"
                    " 'America/New_York'. Defaults to UTC."
                ),
            }
        },
        "required": [],
    },
    tier="read",

    risk_category="read_only_info",    timeout_s=5,
    cacheable=True,
    cache_ttl_s=5,
    idempotent=True,
    parallel_safe=True,
    tags=("time", "date", "clock", "timezone", "now", "today"),
)


def resolve_timezone(name: str | None) -> str:
    """The timezone to use: the argument if valid, else UTC."""
    return name if name and ZoneInfo(name) else "UTC"


async def run(args: dict[str, Any], ctx: ToolContext) -> ToolResult:
    requested = args.get("timezone")
    if requested is not None and (not isinstance(requested, str) or not requested.strip()):
        return ToolResult.failure(
            "INVALID_ARGS",
            "timezone must be a non-empty IANA name if given.",
            hint="Try 'UTC', 'Asia/Kolkata' or 'America/New_York'.",
        )
    zone = "UTC"
    if isinstance(requested, str) and requested.strip():
        try:
            ZoneInfo(requested)
            zone = requested
        except ZoneInfoNotFoundError:
            suggestions = get_close_matches(requested, _available_zones(), n=3)
            hint = ", ".join(suggestions) if suggestions else "check the spelling of the zone name"
            return ToolResult.failure(
                "INVALID_ARGS",
                f"{requested!r} is not an IANA timezone name.",
                hint=f"Close matches: {hint}.",
            )
    now = datetime.now(ZoneInfo(zone))
    return ToolResult.success(
        {
            "timezone": zone,
            "iso": now.isoformat(timespec="seconds"),
            "date": now.date().isoformat(),
            "time": now.time().isoformat(timespec="seconds"),
            "weekday": now.strftime("%A"),
            "utc_offset": now.strftime("%z"),
            "epoch_seconds": int(time.time()),
        }
    )
