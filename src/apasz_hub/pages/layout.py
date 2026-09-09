"""Shared page chrome."""

from __future__ import annotations

from typing import Final

from apasz_hub.framework import A, Footer, HtmlNode, Li, Nav, P, Ul
from apasz_hub.routes.paths import SiteRoute

_SITE_NAVIGATION: Final[tuple[tuple[SiteRoute, str], ...]] = ((SiteRoute.HOME, "Home"),)


def site_footer(current_page: SiteRoute | None = None) -> HtmlNode:
    """Render the shared footer and indicate the active page."""

    return Footer(
        Nav(
            Ul(
                *(
                    _navigation_link(page, label, current_page)
                    for page, label in _SITE_NAVIGATION
                ),
                cls="site-nav__list",
            ),
            aria_label="Site navigation",
            cls="site-nav",
        ),
        P("Critical Thinking is a Virtue", cls="signature"),
        cls="site-footer",
    )


def _navigation_link(
    page: SiteRoute,
    label: str,
    current_page: SiteRoute | None,
) -> HtmlNode:
    """Build one footer navigation link with its current-page state."""

    attributes = {"href": page.value, "cls": "site-nav__link"}
    if page is current_page:
        attributes["aria_current"] = "page"
    return Li(A(label, **attributes))
