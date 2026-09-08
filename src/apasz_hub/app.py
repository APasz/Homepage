"""FastHTML application assembly for the APasz public hub."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from apasz_hub.components import document_headers, theme_color_meta
from apasz_hub.data import (
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
from apasz_hub.pages import SitePage, configuration_page, homepage
from apasz_hub.theme import (
    THEME_STYLESHEET_CACHE_CONTROL,
    THEME_STYLESHEET_URL,
    ThemeColorDataError,
    load_theme_colors,
    save_theme_colors,
    theme_stylesheet,
)

STATIC_DIRECTORY = Path(__file__).parent / "static"
LINK_CARD_DRAFT_REVISION_HEADER: Final = "X-Link-Card-Draft-Revision"
DYNAMIC_PAGE_CACHE_CONTROL: Final = "no-store"
LINK_CARD_STORE: Final = LinkCardStore()
GITHUB_REPOSITORY_REFRESHER: Final = GithubRepositoryCountRefresher(
    GITHUB_REPOSITORY_COUNTS,
    LINK_CARD_STORE.published_cards,
)


async def _start_application() -> None:
    """Load LinkCards once, then refresh GitHub metadata in the background."""

    LINK_CARD_STORE.load()
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
app.add_middleware(PublicSiteHeadersMiddleware)
mount_static_files(app, path="/static", directory=STATIC_DIRECTORY)


@app.get(SitePage.HOME.value)
async def home() -> RouteResponse:
    """Render the public hub."""

    colors = load_theme_colors()
    return (
        theme_color_meta(colors),
        await homepage(LINK_CARD_STORE.published_cards()),
        response_header("Cache-Control", DYNAMIC_PAGE_CACHE_CONTROL),
    )


@app.get(SitePage.CONFIG.value)
async def config(
    saved: str | None = None,
    link_cards_saved: str | None = None,
) -> RouteResponse:
    """Render persisted palette and in-memory LinkCard draft controls."""

    colors = load_theme_colors()
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
        ),
        response_header("Cache-Control", DYNAMIC_PAGE_CACHE_CONTROL),
    )


@app.post(SitePage.CONFIG_COLOURS_SAVE.value)
async def save_config(request: Request) -> RedirectResponse:
    """Validate and persist one submitted shared palette."""

    try:
        form = await request.form()
        save_theme_colors(dict(form))
    except ThemeColorDataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(f"{SitePage.CONFIG.value}?saved=1", status_code=303)


@app.post(SitePage.CONFIG_LINK_CARDS_DRAFT.value)
async def update_link_card_draft(request: Request) -> Response:
    """Validate and retain the submitted LinkCard draft without writing JSON."""

    try:
        LINK_CARD_STORE.update_draft(
            await request.form(),
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


@app.post(SitePage.CONFIG_LINK_CARDS_SAVE.value)
async def save_link_card_draft(request: Request) -> RedirectResponse:
    """Persist the submitted in-memory LinkCard draft and publish it."""

    try:
        LINK_CARD_STORE.update_draft(await request.form())
        LINK_CARD_STORE.save_draft()
    except LinkCardDataError as error:
        raise HTTPException(status_code=422, detail=str(error)) from error
    return RedirectResponse(
        f"{SitePage.CONFIG.value}?link_cards_saved=1",
        status_code=303,
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


@app.get(THEME_STYLESHEET_URL)
async def theme_css() -> Response:
    """Serve palette custom properties from their typed source of truth."""

    return Response(
        theme_stylesheet(load_theme_colors()),
        media_type="text/css",
        headers={"Cache-Control": THEME_STYLESHEET_CACHE_CONTROL},
    )
