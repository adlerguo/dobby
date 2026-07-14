from collections.abc import Awaitable, Callable
from typing import Any

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class BodySizeLimitMiddleware:
    def __init__(self, app: ASGIApp, max_body_bytes: int) -> None:
        self.app = app
        self.max_body_bytes = max_body_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        content_length = self._content_length(scope)
        if content_length is not None and content_length > self.max_body_bytes:
            await self._send_too_large(send)
            return

        if content_length is not None:
            await self.app(scope, receive, send)
            return

        messages: list[Message] = []
        total = 0
        while True:
            message = await receive()
            messages.append(message)
            if message["type"] == "http.disconnect":
                return
            if message["type"] != "http.request":
                continue

            total += len(message.get("body", b""))
            if total > self.max_body_bytes:
                await self._send_too_large(send)
                return
            if not message.get("more_body", False):
                break

        replay = self._replay_receive(messages)
        await self.app(scope, replay, send)

    def _content_length(self, scope: Scope) -> int | None:
        for name, value in scope.get("headers", []):
            if name == b"content-length":
                try:
                    return int(value)
                except ValueError:
                    return None
        return None

    def _replay_receive(self, messages: list[Message]) -> Callable[[], Awaitable[Message]]:
        async def receive() -> Message:
            if messages:
                return messages.pop(0)
            return {"type": "http.request", "body": b"", "more_body": False}

        return receive

    async def _send_too_large(self, send: Send) -> None:
        response = JSONResponse(
            status_code=413,
            content={
                "error": {
                    "code": "request_too_large",
                    "message": f"Request body exceeds {self.max_body_bytes} bytes.",
                }
            },
        )
        await response({}, self._empty_receive, send)

    async def _empty_receive(self) -> dict[str, Any]:
        return {"type": "http.request", "body": b"", "more_body": False}
