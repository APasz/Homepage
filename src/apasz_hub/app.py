"""FastHTML application assembly for the APasz public hub."""

from __future__ import annotations

from collections.abc import Mapping
from logging import getLogger
from pathlib import Path
from typing import Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import PlainTextResponse, RedirectResponse, Response

from apasz_hub import config_security
from apasz_hub.components import document_headers, theme_color_meta
from apasz_hub.data import (
    LINK_CARD_DELETE_INDEX_FORM_NAME,
    SITE,
    LinkCardDataError,
    LinkCardDraftConflictError,
    LinkCardStore,
    load_icon_assets,
)
from apasz_hub.framework import (
    RouteResponse,
    create_app,
    mount_static_files,
    response_header,
)
from apasz_hub.github import (
    GITHUB_REPOSITORY_COUNTS,
    GithubRepositoryCountRefresher,
)
from apasz_hub.middleware import PublicSiteHeadersMiddleware
from apasz_hub.pages import (
    SitePage,
    configuration_login_page,
    configuration_page,
    homepage,
)
from apasz_hub.theme import (
    THEME_STYLESHEET_CACHE_CONTROL,
    THEME_STYLESHEET_URL,
    ThemeColorDataError,
    ThemeColorStore,
    theme_stylesheet,
)

STATIC_DIRECTORY = Path(__file__).parent / "static"
LINK_CARD_DRAFT_REVISION_HEADER: Final = "X-Link-Card-Draft-Revision"
DYNAMIC_PAGE_CACHE_CONTROL: Final = "no-store"
LOGGER = getLogger(__name__)
LINK_CARD_STORE: Final = LinkCardStore()
THEME_COLOR_STORE: Final = ThemeColorStore()
GITHUB_REPOSITORY_REFRESHER: Final = GithubRepositoryCountRefresher(
    GITHUB_REPOSITORY_COUNTS,
    LINK_CARD_STORE.published_cards,
)


async def _start_application() -> None:
    """Load published snapshots, then refresh GitHub metadata in the background."""

    THEME_COLOR_STORE.load()
    LINK_CARD_STORE.load()
    config_security.CONFIG_ACCESS.settings()
    GITHUB_REPOSITORY_REFRESHER.start()


async def _stop_application() -> None:
    """Stop the GitHub refresher before the application event loop closes."""

    await GITHUB_REPOSITORY_REFRESHER.stop()


app = create_app(
    title=SITE.title,
    headers=document_headers(),
    on_startup=_start_application,
    on_shutdown=_stop_application,
)
app.add_middleware(config_security.ConfigAccessMiddleware)
app.add_middleware(PublicSiteHeadersMiddleware)
mount_static_files(app, path="/static", directory=STATIC_DIRECTORY)


@app.get(SitePage.HOME.value)
async def home() -> RouteResponse:
    """Render the public hub."""

    colors = THEME_COLOR_STORE.published_colors()
    return (
        theme_color_meta(colors),
        await homepage(LINK_CARD_STORE.published_cards()),
        response_header("Cache-Control", DYNAMIC_PAGE_CACHE_CONTROL),
    )


@app.get(SitePage.CONFIG.value)
async def config(
    request: Request,
    saved: str | None = None,
    link_cards_saved: str | None = None,
) -> RouteResponse:
    """Render the published palette and in-memory LinkCard draft controls."""

    colors = THEME_COLOR_STORE.published_colors()
    return (
        theme_color_meta(colors),
        configuration_page(
            colors,
            LINK_CARD_STORE.draft_cards(),
            load_icon_assets(),
            colours_saved=saved == "1",
            link_cards_saved=link_cards_saved == "1",
            link_cards_dirty=LINK_CARD_STORE.is_draft_dirty,
            link_cards_draft_revision=LINK_CARD_STORE.draft_revision,
            csrf_token=config_security.session_from_request(request).csrf_token,
        ),
        response_header("Cache-Control", DYNAMIC_PAGE_CACHE_CONTROL),
    )


@app.get(SitePage.CONFIG_LOGIN.value)
async def config_login(failed: str | None = None) -> RouteResponse:
    """Render the sole-administrator configuration login form."""

    return (
        configuration_login_page(failed=failed == "1"),
        response_header("Cache-Control", DYNAMIC_PAGE_CACHE_CONTROL),
    )


@app.post(SitePage.CONFIG_LOGIN.value)
async def login(request: Request) -> Response:
    """Verify an admin password and issue a new short-lived session."""

    form = await request.form()
    password_value = form.get(config_security.CONFIG_PASSWORD_FORM_NAME)
    password = password_value if isinstance(password_value, str) else ""
    client = config_security.configuration_client(request)
    outcome = config_security.CONFIG_ACCESS.login(client, password)
    if outcome.result is config_security.LoginResult.AUTHENTICATED:
        response = RedirectResponse(SitePage.CONFIG.value, status_code=303)
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
            f"{SitePage.CONFIG_LOGIN.value}?failed=1",
            status_code=303,
        )
    raise HTTPException(status_code=503, detail="Configuration access is unavailable.")


@app.post(SitePage.CONFIG_LOGOUT.value)
async def logout(request: Request) -> RedirectResponse:
    """Invalidate the active configuration session and clear its cookie."""

    await config_security.configuration_form(request)
    settings = config_security.CONFIG_ACCESS.settings()
    if settings is None:
        raise HTTPException(
            status_code=503, detail="Configuration access is unavailable."
        )
    client = config_security.configuration_client(request)
    session_id = request.cookies.get(
        config_security.configuration_session_cookie_name(settings),
    )
    config_security.CONFIG_ACCESS.logout(session_id)
    response = RedirectResponse(SitePage.CONFIG_LOGIN.value, status_code=303)
    config_security.clear_configuration_session_cookie(response, settings)
    LOGGER.info("Configuration logout completed from %s.", client)
    return response


@app.post(SitePage.CONFIG_COLOURS_SAVE.value)
async def save_config(request: Request) -> RedirectResponse:
    """Validate, persist, and publish one submitted shared palette."""

    try:
        THEME_COLOR_STORE.save(await _configuration_form_values(request))
    except ThemeColorDataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _log_configuration_change(request, "saved site colours")
    return RedirectResponse(f"{SitePage.CONFIG.value}?saved=1", status_code=303)


@app.post(SitePage.CONFIG_LINK_CARDS_DRAFT.value)
async def update_link_card_draft(request: Request) -> Response:
    """Validate and retain the submitted LinkCard draft without writing JSON."""

    try:
        LINK_CARD_STORE.update_draft(
            await _configuration_form_values(request),
            expected_revision=_link_card_draft_revision(request),
        )
    except LinkCardDraftConflictError as error:
        raise HTTPException(status_code=409, detail=str(error)) from error
    except LinkCardDataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return Response(
        status_code=204,
        headers={
            "Cache-Control": "no-store",
            LINK_CARD_DRAFT_REVISION_HEADER: str(LINK_CARD_STORE.draft_revision),
        },
    )


@app.post(SitePage.CONFIG_LINK_CARDS_ADD.value)
async def add_link_card(request: Request) -> RedirectResponse:
    """Apply current edits and append an unpublished LinkCard draft entry."""

    try:
        LINK_CARD_STORE.add_draft_card_from_form(
            await _configuration_form_values(request),
        )
    except LinkCardDataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _log_configuration_change(request, "added a link-card draft entry")
    return RedirectResponse(SitePage.CONFIG.value, status_code=303)


@app.post(SitePage.CONFIG_LINK_CARDS_DELETE.value)
async def delete_link_card(request: Request) -> RedirectResponse:
    """Apply current edits and remove one unpublished LinkCard draft entry."""

    form_values = await _configuration_form_values(request)
    try:
        index = _link_card_delete_index(form_values)
        form_values.pop(LINK_CARD_DELETE_INDEX_FORM_NAME)
        LINK_CARD_STORE.delete_draft_card_from_form(form_values, index)
    except LinkCardDataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _log_configuration_change(request, "deleted a link-card draft entry")
    return RedirectResponse(SitePage.CONFIG.value, status_code=303)


@app.post(SitePage.CONFIG_LINK_CARDS_SAVE.value)
async def save_link_card_draft(request: Request) -> RedirectResponse:
    """Persist the submitted in-memory LinkCard draft and publish it."""

    try:
        LINK_CARD_STORE.update_draft(
            await _configuration_form_values(request),
        )
        LINK_CARD_STORE.save_draft()
    except LinkCardDataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    _log_configuration_change(request, "published link cards")
    return RedirectResponse(
        f"{SitePage.CONFIG.value}?link_cards_saved=1",
        status_code=303,
    )


async def _configuration_form_values(request: Request) -> dict[str, object]:
    """Read a CSRF-protected form and remove security metadata from its values."""

    form = await config_security.configuration_form(request)
    values: dict[str, object] = dict(form)
    values.pop(config_security.CONFIG_CSRF_FORM_NAME, None)
    return values


def _log_configuration_change(request: Request, action: str) -> None:
    """Record an authenticated state change without recording submitted content."""

    LOGGER.info(
        "Configuration %s from %s.",
        action,
        config_security.configuration_client(request),
    )


def _link_card_draft_revision(request: Request) -> int | None:
    """Read an optional non-negative revision sent by asynchronous draft updates."""

    value = request.headers.get(LINK_CARD_DRAFT_REVISION_HEADER)
    if value is None:
        return None
    try:
        revision = int(value)
    except ValueError as error:
        raise LinkCardDataError(
            "Link-card draft revision must be an integer."
        ) from error
    if revision < 0:
        raise LinkCardDataError("Link-card draft revision must not be negative.")
    return revision


def _link_card_delete_index(values: Mapping[str, object]) -> int:
    """Read the non-negative draft-card index selected for deletion."""

    value = values.get(LINK_CARD_DELETE_INDEX_FORM_NAME)
    if not isinstance(value, str):
        raise LinkCardDataError("Link-card delete request must identify a card.")
    try:
        index = int(value)
    except ValueError as error:
        raise LinkCardDataError("Link-card delete index must be an integer.") from error
    if index < 0:
        raise LinkCardDataError("Link-card delete index must not be negative.")
    return index


@app.get(THEME_STYLESHEET_URL)
async def theme_css() -> Response:
    """Serve custom properties from the published palette snapshot."""

    return Response(
        theme_stylesheet(THEME_COLOR_STORE.published_colors()),
        media_type="text/css",
        headers={"Cache-Control": THEME_STYLESHEET_CACHE_CONTROL},
    )
