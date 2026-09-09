"""Public error-page compositions."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import IntEnum
from typing import Final

from apasz_hub.components import ButtonStyle, button_class
from apasz_hub.data import SITE
from apasz_hub.framework import H1, A, Div, HtmlNode, Main, P, Section, Title
from apasz_hub.routes.paths import SiteRoute

from .layout import site_footer


class ErrorPageStatus(IntEnum):
    """HTTP failures with a dedicated public page."""

    NOT_FOUND = 404
    INTERNAL_SERVER_ERROR = 500


@dataclass(frozen=True, slots=True)
class _ErrorPageCopy:
    """The visible content associated with one public error status."""

    label: str
    heading: str
    message: str


_ERROR_PAGE_COPIES: Final[Mapping[ErrorPageStatus, _ErrorPageCopy]] = {
    ErrorPageStatus.NOT_FOUND: _ErrorPageCopy(
        label="Not found",
        heading="Page not found",
        message="This address does not point to a page on this site.",
    ),
    ErrorPageStatus.INTERNAL_SERVER_ERROR: _ErrorPageCopy(
        label="Server error",
        heading="Something went wrong",
        message="The site hit an unexpected problem. Please try again shortly.",
    ),
}

if set(_ERROR_PAGE_COPIES) != set(ErrorPageStatus):
    raise RuntimeError("Every public error status must have page copy.")


def error_page(
    status: ErrorPageStatus,
    *,
    site_title: str = SITE.title,
) -> tuple[HtmlNode, HtmlNode]:
    """Build a complete public error-page body and document title."""

    page_copy = _ERROR_PAGE_COPIES[status]
    return (
        Title(f"{status.value} · {site_title}"),
        Main(
            Div(
                Section(
                    P(str(status.value), aria_hidden="true", cls="error-page__code"),
                    P(page_copy.label, cls="error-page__eyebrow"),
                    H1(page_copy.heading, cls="error-page__title"),
                    P(page_copy.message, cls="error-page__message"),
                    Div(
                        A(
                            "Back to home",
                            href=SiteRoute.HOME.value,
                            cls=button_class(ButtonStyle.ALPHA),
                        ),
                        cls="action-buttons error-page__actions",
                    ),
                    aria_label=f"HTTP {status.value} error",
                    cls="error-page__panel",
                ),
                cls="error-page__content",
            ),
            site_footer(),
            cls="site-shell error-page",
        ),
    )
