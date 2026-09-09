"""ASGI application composition for the APasz public hub."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, Response

from apasz_hub import config_security
from apasz_hub.components import document_asset_headers
from apasz_hub.data import SITE
from apasz_hub.errors import error_page_response
from apasz_hub.framework import (
    ErrorHandler,
    ExceptionHandlerKey,
    FastHTMLApp,
    LifecycleHook,
    PageResponse,
    create_app,
    mount_static_files,
)
from apasz_hub.middleware import PublicSiteHeadersMiddleware
from apasz_hub.pages import ErrorPageStatus
from apasz_hub.routes.authentication import (
    register_configuration_authentication_routes,
)
from apasz_hub.routes.configuration import register_configuration_routes
from apasz_hub.routes.public import register_public_routes
from apasz_hub.services import ApplicationServices

STATIC_DIRECTORY: Final = Path(__file__).parent / "static"


def create_application(services: ApplicationServices) -> FastHTMLApp:
    """Assemble an ASGI application around one explicit service bundle."""

    app = create_app(
        title=SITE.title,
        headers=document_asset_headers(),
        exception_handlers=_error_handlers(services),
        on_startup=_startup(services),
        on_shutdown=_shutdown(services),
    )
    app.add_middleware(config_security.ConfigAccessMiddleware)
    app.add_middleware(PublicSiteHeadersMiddleware)
    mount_static_files(app, path="/static", directory=STATIC_DIRECTORY)
    register_public_routes(app, services)
    register_configuration_authentication_routes(app, services)
    register_configuration_routes(app, services)
    return app


def _error_handlers(
    services: ApplicationServices,
) -> dict[ExceptionHandlerKey, ErrorHandler]:
    """Build full-document handlers for the public HTTP failure pages."""

    handlers: dict[ExceptionHandlerKey, ErrorHandler] = {
        status.value: _error_handler(services, status) for status in ErrorPageStatus
    }
    handlers[HTTPException] = _http_exception_handler(services)
    return handlers


def _error_handler(
    services: ApplicationServices,
    status: ErrorPageStatus,
) -> ErrorHandler:
    """Build one palette-aware FastHTML exception handler."""

    def handle(_request: Request, exception: Exception) -> PageResponse:
        http_exception = exception if isinstance(exception, HTTPException) else None
        return _public_error_response(services, status, http_exception)

    return handle


def _http_exception_handler(services: ApplicationServices) -> ErrorHandler:
    """Build the handler that upgrades declared public 404 and 500 errors."""

    def handle(_request: Request, exception: Exception) -> PageResponse | Response:
        if not isinstance(exception, HTTPException):
            raise TypeError("HTTP exception handler received a non-HTTP exception.")
        try:
            status = ErrorPageStatus(exception.status_code)
        except ValueError:
            return _default_http_exception_response(exception)
        return _public_error_response(services, status, exception)

    return handle


def _public_error_response(
    services: ApplicationServices,
    status: ErrorPageStatus,
    exception: HTTPException | None = None,
) -> PageResponse:
    """Build an error page while retaining declared HTTP headers."""

    headers = None if exception is None else exception.headers
    return error_page_response(
        services.theme_colors.published_colors(),
        status,
        metadata=services.open_graph.published_metadata(),
        headers=headers,
    )


def _default_http_exception_response(exception: HTTPException) -> Response:
    """Match Starlette's response behavior for statuses without a public page."""

    if exception.status_code in {204, 304}:
        return Response(status_code=exception.status_code, headers=exception.headers)
    return PlainTextResponse(
        exception.detail,
        status_code=exception.status_code,
        headers=exception.headers,
    )


def _startup(services: ApplicationServices) -> LifecycleHook:
    """Create the application-start hook for one service bundle."""

    async def start_application() -> None:
        services.open_graph.load()
        services.theme_colors.load()
        services.link_cards.load()
        config_security.CONFIG_ACCESS.settings()
        services.github_repository_refresher.start()

    return start_application


def _shutdown(services: ApplicationServices) -> LifecycleHook:
    """Create the application-stop hook for one service bundle."""

    async def stop_application() -> None:
        await services.github_repository_refresher.stop()

    return stop_application
