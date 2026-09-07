"""A narrow typed boundary around FastHTML's dynamic component API.

FastHTML and fastcore currently ship without complete type stubs. Keeping their
dynamic surface here lets the rest of the application retain strict type
checking while still using FastHTML components directly.
"""

from __future__ import annotations

import os
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Final, Protocol, cast

from fasthtml import common as fh
from starlette.staticfiles import StaticFiles
from starlette.types import Receive, Scope, Send

DEVELOPMENT_HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 5001
DEFAULT_PRODUCTION_HOST: Final = DEVELOPMENT_HOST


class HtmlNode:
    """Opaque static type for a FastHTML node returned by this module."""


type HtmlChild = HtmlNode | str
type RouteHandler = Callable[[], Awaitable[HtmlNode]]
type RouteDecorator = Callable[[RouteHandler], RouteHandler]


class Component(Protocol):
    """A FastHTML tag factory with the subset of attributes this app needs."""

    def __call__(self, *children: HtmlChild, **attributes: str) -> HtmlNode:
        """Create an opaque FastHTML node."""
        ...


class FastHTMLApp(Protocol):
    """The small portion of the FastHTML application API used by v1."""

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Serve the ASGI application."""
        ...

    def get(self, path: str) -> RouteDecorator:
        """Create a GET route decorator."""
        ...

    def mount(self, path: str, app: object, *, name: str) -> None:
        """Mount an ASGI application beneath this app."""
        ...

    def add_middleware(self, middleware_class: type[object]) -> None:
        """Add an ASGI response middleware."""
        ...


def create_app(*, title: str, headers: tuple[HtmlNode, ...]) -> FastHTMLApp:
    """Create the small FastHTML application shell."""

    return cast(
        FastHTMLApp,
        fh.FastHTML(
            title=title,
            hdrs=headers,
            default_hdrs=False,
            htmx=False,
            surreal=False,
            htmlkw={"lang": "en"},
            canonical=False,
            cls="site-body",
        ),
    )


def mount_static_files(app: FastHTMLApp, *, path: str, directory: Path) -> None:
    """Mount the app's small static asset directory."""

    app.mount(path, StaticFiles(directory=str(directory)), name="static")


def serve_development(appname: str) -> None:
    """Run the local server with live reload enabled."""

    _serve(
        appname=appname,
        host=DEVELOPMENT_HOST,
        port=_server_port(),
        reload=True,
    )


def serve_production(appname: str) -> None:
    """Run the production server without reload or a server-identifying header."""

    _serve(
        appname=appname,
        host=_production_host(),
        port=_server_port(),
        proxy_headers=False,
        reload=False,
        server_header=False,
    )


def _serve(**options: object) -> None:
    """Invoke FastHTML's dynamically delegated Uvicorn wrapper."""

    fh.serve(**options)


def _server_port() -> int:
    """Read and validate the conventional deployment port override."""

    raw_port = os.environ.get("PORT")
    if raw_port is None:
        return DEFAULT_PORT
    try:
        port = int(raw_port)
    except ValueError as error:
        raise ValueError("PORT must be an integer between 1 and 65535.") from error
    if not 1 <= port <= 65535:
        raise ValueError("PORT must be an integer between 1 and 65535.")
    return port


def _production_host() -> str:
    """Return an explicitly configurable production bind address."""

    host = os.environ.get("APASZ_HUB_HOST", DEFAULT_PRODUCTION_HOST).strip()
    if not host:
        raise ValueError("APASZ_HUB_HOST must not be empty.")
    return host


def render(*nodes: HtmlNode) -> str:
    """Render FastHTML nodes for small deterministic component tests."""

    return cast(str, fh.to_xml(nodes))


def _component(value: object) -> Component:
    """Expose a dynamic FastHTML component through the typed tag contract."""

    return cast(Component, value)


A: Component = _component(fh.A)
Article: Component = _component(fh.Article)
Div: Component = _component(fh.Div)
Footer: Component = _component(fh.Footer)
H1: Component = _component(fh.H1)
H2: Component = _component(fh.H2)
Header: Component = _component(fh.Header)
Img: Component = _component(fh.Img)
Li: Component = _component(fh.Li)
Link: Component = _component(fh.Link)
Main: Component = _component(fh.Main)
Meta: Component = _component(fh.Meta)
Nav: Component = _component(fh.Nav)
P: Component = _component(fh.P)
Picture: Component = _component(fh.Picture)
Section: Component = _component(fh.Section)
Script: Component = _component(fh.Script)
Span: Component = _component(fh.Span)
Source: Component = _component(fh.Source)
Ul: Component = _component(fh.Ul)
