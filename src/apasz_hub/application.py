"""ASGI application composition for the APasz public hub."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from apasz_hub import config_security
from apasz_hub.components import document_headers
from apasz_hub.data import SITE
from apasz_hub.framework import (
    FastHTMLApp,
    LifecycleHook,
    create_app,
    mount_static_files,
)
from apasz_hub.middleware import PublicSiteHeadersMiddleware
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
        headers=document_headers(),
        on_startup=_startup(services),
        on_shutdown=_shutdown(services),
    )
    app.add_middleware(config_security.ConfigAccessMiddleware)
    app.add_middleware(PublicSiteHeadersMiddleware)
    mount_static_files(app, path="/static", directory=STATIC_DIRECTORY)
    register_public_routes(app, services)
    register_configuration_authentication_routes(app)
    register_configuration_routes(app, services)
    return app


def _startup(services: ApplicationServices) -> LifecycleHook:
    """Create the application-start hook for one service bundle."""

    async def start_application() -> None:
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
