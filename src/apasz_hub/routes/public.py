"""Public homepage and theme stylesheet routes."""

from __future__ import annotations

from starlette.responses import PlainTextResponse, Response

from apasz_hub.components import document_metadata, theme_color_meta
from apasz_hub.errors import error_page_response
from apasz_hub.framework import (
    FastHTMLApp,
    PageResponse,
    RouteResponse,
    response_header,
)
from apasz_hub.middleware import NO_STORE_CACHE_CONTROL
from apasz_hub.pages import ErrorPageStatus, homepage
from apasz_hub.routes.paths import SiteRoute
from apasz_hub.services import ApplicationServices
from apasz_hub.theme import (
    THEME_STYLESHEET_CACHE_CONTROL,
    THEME_STYLESHEET_URL,
    theme_stylesheet,
)


def register_public_routes(
    app: FastHTMLApp,
    services: ApplicationServices,
) -> None:
    """Register routes available without configuration authentication."""

    async def home() -> RouteResponse:
        """Render the public hub from the published snapshots."""

        metadata = services.open_graph.published_metadata()
        colors = services.theme_colors.published_colors()
        return (
            *document_metadata(metadata),
            theme_color_meta(colors),
            await homepage(
                services.link_cards.published_cards(),
                services.github_repository_counts,
            ),
            response_header("Cache-Control", NO_STORE_CACHE_CONTROL),
        )

    async def theme_css() -> Response:
        """Serve custom properties from the published palette snapshot."""

        return Response(
            theme_stylesheet(services.theme_colors.published_colors()),
            media_type="text/css",
            headers={"Cache-Control": THEME_STYLESHEET_CACHE_CONTROL},
        )

    async def healthz() -> PlainTextResponse:
        """Confirm that the application can accept HTTP requests."""

        return PlainTextResponse(
            "ok",
            headers={"Cache-Control": NO_STORE_CACHE_CONTROL},
        )

    async def not_found() -> PageResponse:
        """Render the public not-found page at its dedicated URL."""

        return error_page_response(
            services.theme_colors.published_colors(),
            ErrorPageStatus.NOT_FOUND,
            metadata=services.open_graph.published_metadata(),
        )

    async def internal_server_error() -> PageResponse:
        """Render the public server-error page at its dedicated URL."""

        return error_page_response(
            services.theme_colors.published_colors(),
            ErrorPageStatus.INTERNAL_SERVER_ERROR,
            metadata=services.open_graph.published_metadata(),
        )

    app.get(SiteRoute.HOME.value)(home)
    app.get(SiteRoute.HEALTHZ.value)(healthz)
    app.get(SiteRoute.NOT_FOUND.value)(not_found)
    app.get(SiteRoute.INTERNAL_SERVER_ERROR.value)(internal_server_error)
    app.get(THEME_STYLESHEET_URL)(theme_css)
