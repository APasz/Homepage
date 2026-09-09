"""Configuration login and logout routes."""

from __future__ import annotations

from logging import getLogger

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response

from apasz_hub import config_security
from apasz_hub.components import document_metadata
from apasz_hub.framework import FastHTMLApp, RouteResponse, response_header
from apasz_hub.middleware import NO_STORE_CACHE_CONTROL
from apasz_hub.pages import configuration_login_page
from apasz_hub.routes.paths import SiteRoute
from apasz_hub.services import ApplicationServices

LOGGER = getLogger(__name__)


def register_configuration_authentication_routes(
    app: FastHTMLApp,
    services: ApplicationServices,
) -> None:
    """Register the configuration session entry and exit points."""

    async def config_login(failed: str | None = None) -> RouteResponse:
        """Render the sole-administrator configuration login form."""

        metadata = services.open_graph.published_metadata()
        return (
            *document_metadata(metadata),
            configuration_login_page(failed=failed == "1"),
            response_header("Cache-Control", NO_STORE_CACHE_CONTROL),
        )

    async def login(request: Request) -> Response:
        """Verify an admin password and issue a new short-lived session."""

        form = await request.form()
        password_value = form.get(config_security.CONFIG_PASSWORD_FORM_NAME)
        password = password_value if isinstance(password_value, str) else ""
        client = config_security.configuration_client(request)
        outcome = config_security.CONFIG_ACCESS.login(client, password)
        if outcome.result is config_security.LoginResult.AUTHENTICATED:
            response = RedirectResponse(SiteRoute.CONFIG.value, status_code=303)
            config_security.set_configuration_session_cookie(response, outcome)
            LOGGER.info("Configuration login succeeded from %s.", client)
            return response
        if outcome.result is config_security.LoginResult.RATE_LIMITED:
            retry_after_seconds = outcome.retry_after_seconds
            if retry_after_seconds is None:
                raise RuntimeError("Rate-limited login must include a retry duration.")
            LOGGER.warning("Configuration login rate limited from %s.", client)
            return PlainTextResponse(
                "Too many login attempts. Try again later.",
                status_code=429,
                headers={"Retry-After": str(retry_after_seconds)},
            )
        if outcome.result is config_security.LoginResult.INVALID:
            LOGGER.warning("Configuration login failed from %s.", client)
            return RedirectResponse(
                f"{SiteRoute.CONFIG_LOGIN.value}?failed=1",
                status_code=303,
            )
        raise HTTPException(
            status_code=503, detail="Configuration access is unavailable."
        )

    async def logout(request: Request) -> RedirectResponse:
        """Invalidate the active configuration session and clear its cookie."""

        await config_security.configuration_form(request)
        settings = config_security.CONFIG_ACCESS.settings()
        if settings is None:
            raise HTTPException(
                status_code=503,
                detail="Configuration access is unavailable.",
            )
        client = config_security.configuration_client(request)
        session_id = request.cookies.get(
            config_security.configuration_session_cookie_name(settings),
        )
        config_security.CONFIG_ACCESS.logout(session_id)
        response = RedirectResponse(SiteRoute.CONFIG_LOGIN.value, status_code=303)
        config_security.clear_configuration_session_cookie(response, settings)
        LOGGER.info("Configuration logout completed from %s.", client)
        return response

    app.get(SiteRoute.CONFIG_LOGIN.value)(config_login)
    app.post(SiteRoute.CONFIG_LOGIN.value)(login)
    app.post(SiteRoute.CONFIG_LOGOUT.value)(logout)
