"""Where the user is, on demand.

This machine has no GPS hardware, so there is no satellite fix to read. Two
sources are tried, in the order the user chose:

1. **The browser's geolocation API.** Only the client can ask for this, because
   the permission prompt belongs to the window the user is looking at. The
   backend raises a ``kind="location"`` request, the client answers it with
   coordinates, and this call returns them.
2. **IP geolocation.** A plain HTTPS lookup. City-level, and any website you
   visit could work it out too -- which is why it is a fallback and not the
   default, and why the result always says which source produced it.

Either way this only runs when the model actually needs it, never in the
background, and the coordinates are surfaced to the user rather than folded
away silently.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from app.config import settings
from app.services.command_runner import REGISTRY, CommandResult, PendingRequest

LOCATION_TOOL_NAME = "get_location"

# Long enough for a permission dialog to be read and answered, short enough
# that a forgotten prompt does not hang the turn.
_LOCATION_ANSWER_TIMEOUT_SECONDS = 25.0

# A shared free endpoint. It is only ever asked for the caller's own address,
# never for anyone else's, and the response is cached for the process lifetime
# because the machine does not move between two questions.
_IP_LOOKUP_URL = "https://ipapi.co/json/"
_IP_LOOKUP_FALLBACK = "http://ip-api.com/json/"


@dataclass(frozen=True)
class Location:
    latitude: float
    longitude: float
    accuracy_m: float | None
    source: str
    label: str

    def as_text(self) -> str:
        parts = [
            f"Approximate location: {self.label}",
            f"Coordinates: {self.latitude:.5f}, {self.longitude:.5f}",
            f"Source: {self.source}",
        ]
        if self.accuracy_m is not None:
            parts.insert(2, f"Accuracy: about {self.accuracy_m:.0f} m")
        return "\n".join(parts)

    def as_payload(self) -> dict[str, Any]:
        return {
            "latitude": self.latitude,
            "longitude": self.longitude,
            "accuracy_m": self.accuracy_m,
            "source": self.source,
            "label": self.label,
        }


def _valid_coordinate(payload: dict[str, Any]) -> tuple[float, float, float | None] | None:
    try:
        latitude = float(payload["latitude"])
        longitude = float(payload["longitude"])
    except (KeyError, TypeError, ValueError):
        return None
    if not (-90.0 <= latitude <= 90.0 and -180.0 <= longitude <= 180.0):
        return None
    accuracy = payload.get("accuracy_m")
    try:
        accuracy_value = float(accuracy) if accuracy is not None else None
    except (TypeError, ValueError):
        accuracy_value = None
    return latitude, longitude, accuracy_value


_cached_ip_location: Location | None = None


async def _lookup_ip_location() -> Location | None:
    """City-level position from the outgoing IP. Cached for the process."""
    global _cached_ip_location
    if _cached_ip_location is not None:
        return _cached_ip_location

    for url in (_IP_LOOKUP_URL, _IP_LOOKUP_FALLBACK):
        try:
            process = await asyncio.create_subprocess_exec(
                "curl", "--silent", "--show-error", "--fail", "--max-time", "8",
                "--proto", "=https,http", url,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
            )
        except OSError:
            continue
        try:
            raw, _ = await asyncio.wait_for(process.communicate(), timeout=10)
        except (TimeoutError, asyncio.TimeoutError):
            process.kill()
            continue
        if process.returncode != 0:
            continue
        import json

        try:
            body = json.loads(raw.decode("utf-8", "replace"))
        except ValueError:
            continue
        if not isinstance(body, dict):
            continue
        # The two providers disagree on field names.
        latitude = body.get("latitude", body.get("lat"))
        longitude = body.get("longitude", body.get("lon"))
        if body.get("status") == "fail" or latitude is None or longitude is None:
            continue
        try:
            lat = float(latitude)
            lon = float(longitude)
        except (TypeError, ValueError):
            continue
        if not (-90.0 <= lat <= 90.0 and -180.0 <= lon <= 180.0):
            continue
        city = str(body.get("city") or "").strip()
        region = str(body.get("region") or body.get("regionName") or "").strip()
        country = str(body.get("country") or body.get("country_name") or "").strip()
        label = ", ".join(part for part in (city, region, country) if part) or "unknown area"
        _cached_ip_location = Location(
            latitude=lat,
            longitude=lon,
            accuracy_m=None,
            source="ip (approximate, no GPS hardware on this machine)",
            label=label,
        )
        return _cached_ip_location
    return None


async def ask_the_client_for_location(
    conversation_id: str, user_id: str
) -> Location | None:
    """Ask the open window for a fix, and wait for it to answer."""
    request = PendingRequest(
        request_id=uuid4().hex,
        conversation_id=conversation_id,
        user_id=user_id,
        command="Allow Pentagon to use your location for this answer",
        reason="The answer needs to know roughly where you are.",
        created_at=time.time(),
        detail="",
        kind="location",
    )
    REGISTRY.submit(request)
    approved = await REGISTRY.wait(request, _LOCATION_ANSWER_TIMEOUT_SECONDS)
    if not approved:
        return None
    coordinates = _valid_coordinate(request.value)
    if coordinates is None:
        return None
    latitude, longitude, accuracy = coordinates
    return Location(
        latitude=latitude,
        longitude=longitude,
        accuracy_m=accuracy,
        source="browser geolocation",
        label=f"{latitude:.5f}, {longitude:.5f}",
    )


LOCATION_TOOL_SCHEMA = {
    "type": "function",
    "function": {
        "name": LOCATION_TOOL_NAME,
        "description": (
            "Find out roughly where the user is, for questions that depend on "
            "it (nearby places, local time, weather). This is only used when the "
            "question genuinely needs it, never in advance. It asks the app "
            "window for a fix and falls back to a coarse network estimate. The "
            "user can decline, in which case answer without assuming a place."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "reason": {
                    "type": "string",
                    "description": "One short sentence on why the location is needed.",
                }
            },
            "required": [],
        },
    },
}

# Location is read-only information from the user's perspective.
LOCATION_TOOL_SCHEMA["_risk_category"] = "read_only_info"


async def run_location_tool(
    arguments: dict[str, Any] | None,
    *,
    conversation_id: str,
    user_id: str,
    reason: str = "",
) -> CommandResult:
    """Resolve a position, preferring the browser and falling back to the IP."""
    display = "Find the user's approximate location"
    if not (settings.location_enabled and getattr(settings, "command_tool_enabled", False)):
        return _result(display, stderr=disabled_message(), exit_code=1)

    started = time.perf_counter()
    location = await ask_the_client_for_location(conversation_id, user_id)
    if location is None:
        location = await _lookup_ip_location()
    if location is None:
        return _result(
            display,
            stderr=(
                "No location is available: the user did not share one and the "
                "network lookup failed. Ask them where they are instead of "
                "guessing."
            ),
            exit_code=1,
            started=started,
        )
    return _result(
        display,
        stdout=location.as_text(),
        started=started,
        payload=location.as_payload(),
    )


def disabled_message() -> str:
    return (
        "Location is switched off on this server, so the user's position is "
        "not available. Ask them directly instead of guessing."
    )


def _result(
    display: str,
    *,
    stdout: str = "",
    stderr: str = "",
    exit_code: int = 0,
    started: float | None = None,
    payload: dict[str, Any] | None = None,
) -> CommandResult:
    duration = 0.0 if started is None else round((time.perf_counter() - started) * 1000, 2)
    result = CommandResult(
        command=display,
        exit_code=exit_code,
        stdout=stdout,
        stderr=stderr,
        duration_ms=duration,
        auto_approved=False,
    )
    if payload:
        result.value = payload
    return result