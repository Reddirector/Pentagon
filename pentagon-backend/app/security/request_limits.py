"""ASGI request-body limits that apply before route parsing or file buffering."""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any


class RequestBodyLimitMiddleware:
    def __init__(self, app: Any, *, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: dict[str, Any], receive: Callable[..., Awaitable[Any]], send: Callable[..., Awaitable[Any]]) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        content_length = next(
            (value for key, value in scope.get("headers", []) if key.lower() == b"content-length"),
            None,
        )
        if content_length is not None:
            try:
                declared = int(content_length)
            except ValueError:
                await self._reject(send, 400, "Invalid Content-Length header.")
                return
            if declared < 0:
                await self._reject(send, 400, "Invalid Content-Length header.")
                return
            if declared > self.max_bytes:
                await self._reject(send, 413, "Request body is too large.")
                return

        seen = 0
        rejected = False

        async def limited_receive() -> Any:
            nonlocal seen, rejected
            if rejected:
                return {"type": "http.disconnect"}
            message = await receive()
            if message.get("type") == "http.request":
                seen += len(message.get("body", b""))
                if seen > self.max_bytes:
                    rejected = True
                    await self._reject(send, 413, "Request body is too large.")
                    return {"type": "http.disconnect"}
            return message

        async def limited_send(message: Any) -> None:
            if not rejected:
                await send(message)

        await self.app(scope, limited_receive, limited_send)

    @staticmethod
    async def _reject(send: Callable[..., Awaitable[Any]], status: int, detail: str) -> None:
        body = json.dumps({"detail": detail}).encode("utf-8")
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
