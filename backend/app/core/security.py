from __future__ import annotations

from collections import defaultdict, deque
import ipaddress
import json
import logging
import re
from threading import Lock
import time
from typing import Any
from uuid import uuid4

from starlette.datastructures import Headers, MutableHeaders
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.config import Settings

logger = logging.getLogger("app.access")
REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._-]{8,128}$")


def _client_ip(scope: Scope, settings: Settings) -> str:
    peer = str(scope.get("client", ("unknown", 0))[0])
    try:
        peer_address = ipaddress.ip_address(peer)
    except ValueError:
        return peer
    if not any(peer_address in network for network in settings.trusted_proxy_networks):
        return peer
    forwarded = Headers(scope=scope).get("x-forwarded-for", "")
    for item in forwarded.split(","):
        candidate = item.strip()
        try:
            ipaddress.ip_address(candidate)
            return candidate
        except ValueError:
            continue
    return peer


class RequestBodyLimitMiddleware:
    def __init__(self, app: ASGIApp, max_bytes: int) -> None:
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = Headers(scope=scope)
        content_length = headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    await JSONResponse(
                        {"detail": "Request body exceeds the configured limit."}, status_code=413
                    )(scope, receive, send)
                    return
            except ValueError:
                await JSONResponse({"detail": "Invalid Content-Length header."}, status_code=400)(
                    scope, receive, send
                )
                return

        received = 0

        async def limited_receive() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > self.max_bytes:
                    raise RequestBodyTooLarge
            return message

        try:
            await self.app(scope, limited_receive, send)
        except RequestBodyTooLarge:
            await JSONResponse(
                {"detail": "Request body exceeds the configured limit."}, status_code=413
            )(scope, receive, send)


class RequestBodyTooLarge(Exception):
    pass


class RateLimitMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings
        self._requests: dict[str, deque[float]] = defaultdict(deque)
        self._lock = Lock()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or not self.settings.rate_limit_enabled:
            await self.app(scope, receive, send)
            return
        if scope.get("path") in {
            f"{self.settings.api_v1_prefix}/health",
            f"{self.settings.api_v1_prefix}/health/ready",
        }:
            await self.app(scope, receive, send)
            return

        key = _client_ip(scope, self.settings)
        now = time.monotonic()
        cutoff = now - 60
        with self._lock:
            if key not in self._requests and len(self._requests) >= 10_000:
                key = "__overflow__"
            window = self._requests[key]
            while window and window[0] <= cutoff:
                window.popleft()
            if len(window) >= self.settings.rate_limit_requests_per_minute:
                retry_after = max(1, int(60 - (now - window[0])))
                response = JSONResponse({"detail": "Rate limit exceeded."}, status_code=429)
                response.headers["Retry-After"] = str(retry_after)
                await response(scope, receive, send)
                return
            window.append(now)
        await self.app(scope, receive, send)


class SecurityHeadersAndLoggingMiddleware:
    def __init__(self, app: ASGIApp, settings: Settings) -> None:
        self.app = app
        self.settings = settings

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        incoming_id = Headers(scope=scope).get("x-request-id", "")
        request_id = incoming_id if REQUEST_ID_PATTERN.fullmatch(incoming_id) else uuid4().hex
        scope.setdefault("state", {})["request_id"] = request_id
        started = time.perf_counter()
        status_code = 500

        async def send_with_headers(message: Message) -> None:
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = int(message["status"])
                headers = MutableHeaders(scope=message)
                headers["X-Request-ID"] = request_id
                headers["X-Content-Type-Options"] = "nosniff"
                headers["X-Frame-Options"] = "DENY"
                headers["Referrer-Policy"] = "no-referrer"
                headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
                headers["Content-Security-Policy"] = "default-src 'none'; frame-ancestors 'none'"
            await send(message)

        try:
            await self.app(scope, receive, send_with_headers)
        finally:
            event: dict[str, Any] = {
                "event": "http_request",
                "request_id": request_id,
                "method": scope.get("method"),
                "path": scope.get("path"),
                "status_code": status_code,
                "duration_ms": round((time.perf_counter() - started) * 1000, 2),
                "client_ip": _client_ip(scope, self.settings),
            }
            logger.info(json.dumps(event, ensure_ascii=True, separators=(",", ":")))
