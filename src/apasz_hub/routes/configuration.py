"""Authenticated configuration-editor routes."""

from __future__ import annotations

from collections.abc import Mapping
from logging import getLogger
from typing import Final

from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

from apasz_hub import config_security
from apasz_hub.components import document_metadata, theme_color_meta
from apasz_hub.data import (
    LINK_CARD_DELETE_INDEX_FORM_NAME,
    LINK_CARD_MOVE_INDEX_FORM_NAME,
    LinkCardDataError,
    LinkCardDraftConflictError,
    LinkCardMoveDirection,
    load_icon_assets,
)
from apasz_hub.framework import FastHTMLApp, RouteResponse, response_header
from apasz_hub.middleware import NO_STORE_CACHE_CONTROL
from apasz_hub.open_graph import OpenGraphDataError
from apasz_hub.pages import configuration_page
from apasz_hub.routes.paths import SiteRoute
from apasz_hub.services import ApplicationServices
from apasz_hub.theme import ThemeColorDataError

LINK_CARD_DRAFT_REVISION_HEADER: Final = "X-Link-Card-Draft-Revision"
LOGGER = getLogger(__name__)


def register_configuration_routes(
    app: FastHTMLApp,
    services: ApplicationServices,
) -> None:
    """Register the authenticated palette, sharing, and LinkCard editor routes."""

    async def config(
        request: Request,
        saved: str | None = None,
        open_graph_saved: str | None = None,
        link_cards_saved: str | None = None,
    ) -> RouteResponse:
        """Render published site settings and the in-memory LinkCard draft."""

        metadata = services.open_graph.published_metadata()
        colors = services.theme_colors.published_colors()
        link_cards = services.link_cards
        return (
            *document_metadata(
                metadata,
                document_title=f"Configuration · {metadata.title}",
            ),
            theme_color_meta(colors),
            configuration_page(
                colors,
                link_cards.draft_cards(),
                load_icon_assets(),
                metadata=metadata,
                colours_saved=saved == "1",
                open_graph_saved=open_graph_saved == "1",
                link_cards_saved=link_cards_saved == "1",
                link_cards_dirty=link_cards.is_draft_dirty,
                link_cards_draft_revision=link_cards.draft_revision,
                csrf_token=config_security.session_from_request(request).csrf_token,
            ),
            response_header("Cache-Control", NO_STORE_CACHE_CONTROL),
        )

    async def save_config(request: Request) -> RedirectResponse:
        """Validate, persist, and publish one submitted shared palette."""

        try:
            services.theme_colors.save(await _configuration_form_values(request))
        except ThemeColorDataError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        _log_configuration_change(request, "saved site colours")
        return RedirectResponse(f"{SiteRoute.CONFIG.value}?saved=1", status_code=303)

    async def save_open_graph(request: Request) -> RedirectResponse:
        """Validate, persist, and publish submitted social sharing metadata."""

        try:
            services.open_graph.save(await _configuration_form_values(request))
        except OpenGraphDataError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        _log_configuration_change(request, "saved Open Graph metadata")
        return RedirectResponse(
            f"{SiteRoute.CONFIG.value}?open_graph_saved=1",
            status_code=303,
        )

    async def update_link_card_draft(request: Request) -> Response:
        """Validate and retain the submitted LinkCard draft without writing JSON."""

        try:
            services.link_cards.update_draft(
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
                "Cache-Control": NO_STORE_CACHE_CONTROL,
                LINK_CARD_DRAFT_REVISION_HEADER: str(
                    services.link_cards.draft_revision
                ),
            },
        )

    async def add_link_card(request: Request) -> RedirectResponse:
        """Apply current edits and append an unpublished LinkCard draft entry."""

        try:
            services.link_cards.add_draft_card_from_form(
                await _configuration_form_values(request),
            )
        except LinkCardDataError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        _log_configuration_change(request, "added a link-card draft entry")
        return RedirectResponse(SiteRoute.CONFIG.value, status_code=303)

    async def delete_link_card(request: Request) -> RedirectResponse:
        """Apply current edits and remove one unpublished LinkCard draft entry."""

        form_values = await _configuration_form_values(request)
        try:
            index = _link_card_action_index(
                form_values,
                form_name=LINK_CARD_DELETE_INDEX_FORM_NAME,
                action="delete",
            )
            form_values.pop(LINK_CARD_DELETE_INDEX_FORM_NAME)
            services.link_cards.delete_draft_card_from_form(form_values, index)
        except LinkCardDataError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        _log_configuration_change(request, "deleted a link-card draft entry")
        return RedirectResponse(SiteRoute.CONFIG.value, status_code=303)

    async def move_link_card(
        request: Request,
        direction: LinkCardMoveDirection,
    ) -> RedirectResponse:
        """Apply current edits and move one unpublished LinkCard draft entry."""

        form_values = await _configuration_form_values(request)
        try:
            index = _link_card_action_index(
                form_values,
                form_name=LINK_CARD_MOVE_INDEX_FORM_NAME,
                action=f"move {direction.value}",
            )
            form_values.pop(LINK_CARD_MOVE_INDEX_FORM_NAME)
            services.link_cards.move_draft_card_from_form(
                form_values,
                index,
                direction,
            )
        except LinkCardDataError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        _log_configuration_change(
            request,
            f"moved a link-card draft entry {direction.value}",
        )
        return RedirectResponse(SiteRoute.CONFIG.value, status_code=303)

    async def move_link_card_up(request: Request) -> RedirectResponse:
        """Move a LinkCard draft entry one position upward."""

        return await move_link_card(request, LinkCardMoveDirection.UP)

    async def move_link_card_down(request: Request) -> RedirectResponse:
        """Move a LinkCard draft entry one position downward."""

        return await move_link_card(request, LinkCardMoveDirection.DOWN)

    async def save_link_card_draft(request: Request) -> RedirectResponse:
        """Persist the submitted in-memory LinkCard draft and publish it."""

        try:
            services.link_cards.update_draft(await _configuration_form_values(request))
            services.link_cards.save_draft()
        except LinkCardDataError as error:
            raise HTTPException(status_code=422, detail=str(error)) from error
        services.github_repository_refresher.refresh_in_background()
        _log_configuration_change(request, "published link cards")
        return RedirectResponse(
            f"{SiteRoute.CONFIG.value}?link_cards_saved=1",
            status_code=303,
        )

    app.get(SiteRoute.CONFIG.value)(config)
    app.post(SiteRoute.CONFIG_COLOURS_SAVE.value)(save_config)
    app.post(SiteRoute.CONFIG_OPEN_GRAPH_SAVE.value)(save_open_graph)
    app.post(SiteRoute.CONFIG_LINK_CARDS_DRAFT.value)(update_link_card_draft)
    app.post(SiteRoute.CONFIG_LINK_CARDS_ADD.value)(add_link_card)
    app.post(SiteRoute.CONFIG_LINK_CARDS_DELETE.value)(delete_link_card)
    app.post(SiteRoute.CONFIG_LINK_CARDS_MOVE_UP.value)(move_link_card_up)
    app.post(SiteRoute.CONFIG_LINK_CARDS_MOVE_DOWN.value)(move_link_card_down)
    app.post(SiteRoute.CONFIG_LINK_CARDS_SAVE.value)(save_link_card_draft)


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


def _link_card_action_index(
    values: Mapping[str, object],
    *,
    form_name: str,
    action: str,
) -> int:
    """Read the non-negative draft-card index selected by a card action."""

    value = values.get(form_name)
    if not isinstance(value, str):
        raise LinkCardDataError(f"Link-card {action} request must identify a card.")
    try:
        index = int(value)
    except ValueError as error:
        raise LinkCardDataError(
            f"Link-card {action} index must be an integer."
        ) from error
    if index < 0:
        raise LinkCardDataError(
            f"Link-card {action} index must not be negative."
        )
    return index
