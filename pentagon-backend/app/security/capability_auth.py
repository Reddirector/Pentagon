"""Shared API dependency for the local installation capability token."""

from fastapi import Header, HTTPException, Query

from app.services import capability


async def require_capability(
    x_pentagon_capability: str | None = Header(default=None),
    capability_param: str | None = Query(default=None, alias="capability"),
    token_param: str | None = Query(default=None, alias="token"),
) -> None:
    """Reject API calls that do not originate from this Pentagon install."""
    token = x_pentagon_capability or capability_param or token_param
    if not capability.verify(token):
        raise HTTPException(
            status_code=401,
            detail=(
                "This request needs the Pentagon capability token. It proves "
                "the call came from the app rather than from someone who merely "
                "knows a user id."
            ),
        )
