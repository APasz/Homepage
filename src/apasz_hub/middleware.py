"""HTTP response policy for the public site."""

from __future__ import annotations

from typing import Final, cast

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

CONTENT_SECURITY_POLICY: Final = (
    "default-src 'self'; "
    "base-uri 'none'; "
    "connect-src 'self'; "
    "font-src 'self'; "
    "form-action 'self'; "
    "frame-ancestors 'none'; "
    "img-src 'self'; "
    "object-src 'none'; "
    "script-src 'self'; "
    "style-src 'self' 'unsafe-inline'; "
    "style-src-attr 'unsafe-inline'; "
    "style-src-elem 'self'"
)
SECURITY_HEADERS: Final[tuple[tuple[str, str], ...]] = (
    ("Content-Security-Policy", CONTENT_SECURITY_POLICY),
    (
        "Permissions-Policy",
        "camera=(), geolocation=(), microphone=(), payment=(), usb=()",
    ),
    ("Referrer-Policy", "strict-origin-when-cross-origin"),
    ("X-Content-Type-Options", "nosniff"),
    ("X-Frame-Options", "DENY"),
)
STATIC_CACHE_CONTROL: Final = "public, max-age=3600, must-revalidate"
STATIC_PATH_PREFIX: Final = "/static/"


class PublicSiteHeadersMiddleware:
    """Apply a restrictive browser policy and safe static-asset caching."""

    def __init__(self, app: ASGIApp) -> None:
        self._app = app

    async def __call__(
        self,
        scope: Scope,
        receive: Receive,
        send: Send,
    ) -> None:
        if cast(str, scope["type"]) != "http":
            await self._app(scope, receive, send)
            return

        is_static_request = cast(str, scope["path"]).startswith(STATIC_PATH_PREFIX)

        async def send_with_headers(message: Message) -> None:
            if cast(str, message["type"]) == "http.response.start":
                headers = MutableHeaders(
                    raw=cast(list[tuple[bytes, bytes]], message["headers"]),
                )
                for name, value in SECURITY_HEADERS:
                    if name not in headers:
                        headers[name] = value
                status_code = cast(int, message["status"])
                if (
                    is_static_request
                    and (200 <= status_code < 300 or status_code == 304)
                    and "Cache-Control" not in headers
                ):
                    headers["Cache-Control"] = STATIC_CACHE_CONTROL
            await send(message)

        await self._app(scope, receive, send_with_headers)
