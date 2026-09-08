"""Reusable FastHTML components for the APasz hub."""

from __future__ import annotations

from enum import StrEnum
from json import dumps

from apasz_hub.data import (
    FAVICON_URL,
    SITE,
    SITE_SCRIPT_URL,
    SITE_STYLESHEET_URL,
    LinkCard,
    SiteMetadata,
)
from apasz_hub.framework import (
    H2,
    A,
    Article,
    Div,
    HtmlNode,
    Link,
    Meta,
    P,
    Script,
    Span,
)
from apasz_hub.theme import (
    THEME_STYLESHEET_URL,
    ThemeColors,
    ThemeColorToken,
    theme_color,
)


class ButtonStyle(StrEnum):
    """Named shared button treatments built on the secondary palette."""

    ALPHA = "alpha"
    BETA = "beta"


def button_class(style: ButtonStyle) -> str:
    """Return the reusable secondary-style classes for one button treatment."""

    return f"action-button action-button--secondary action-button--{style.value}"


def document_headers(metadata: SiteMetadata = SITE) -> tuple[HtmlNode, ...]:
    """Build document metadata shared by every rendered page."""

    return (
        Meta(charset="utf-8"),
        Meta(name="viewport", content="width=device-width, initial-scale=1"),
        Meta(name="description", content=metadata.description),
        Meta(property="og:type", content="website"),
        Meta(property="og:site_name", content=metadata.title),
        Meta(property="og:title", content=metadata.title),
        Meta(property="og:description", content=metadata.description),
        Meta(property="og:url", content=metadata.canonical_url),
        Meta(name="twitter:card", content="summary"),
        Meta(name="twitter:title", content=metadata.title),
        Meta(name="twitter:description", content=metadata.description),
        Link(rel="canonical", href=metadata.canonical_url),
        Link(rel="icon", type="image/png", sizes="64x64", href=FAVICON_URL),
        Link(rel="stylesheet", href=THEME_STYLESHEET_URL),
        Link(rel="stylesheet", href=SITE_STYLESHEET_URL),
        Script(src=SITE_SCRIPT_URL, defer=""),
    )


def theme_color_meta(colors: ThemeColors) -> HtmlNode:
    """Build a request-fresh browser-chrome colour declaration."""

    canvas = theme_color(colors, ThemeColorToken.CANVAS)
    return Meta(
        name="theme-color",
        content=canvas.value,
        data_theme_color_token=ThemeColorToken.CANVAS.value,
    )


def link_card(card: LinkCard) -> HtmlNode:
    """Render a full-size destination card."""

    metadata = (P(card.metadata, cls="card__metadata"),) if card.metadata else ()
    description: tuple[HtmlNode, ...] = ()
    if card.description is not None or card.copy_to_clipboard:
        description = (
            P(
                card.description or "",
                **_copy_status_attributes(card, "card__description"),
            ),
        )
    return Article(
        _card_anchor(
            card,
            Div(
                Div(
                    H2(card.title, cls="card__title"),
                    *description,
                    cls="card__copy",
                ),
                cls="card__content",
            ),
            _svg_icon(cls="card__icon", frame_cls="card__icon-frame"),
            *metadata,
        ),
        cls=f"hub-card hub-card--{card.tier.value}",
        style=_card_style(card),
    )


def utility_link(card: LinkCard) -> HtmlNode:
    """Render a compact utility destination."""

    attributes = {
        "href": card.href,
        "cls": "utility-link",
        "style": _card_style(card),
    }
    if card.copy_to_clipboard:
        attributes.update(_clipboard_link_attributes(card))
    attributes.update(_external_link_attributes(card))
    return A(*_utility_link_contents(card), **attributes)


def _utility_link_contents(card: LinkCard) -> tuple[HtmlNode, HtmlNode]:
    detail: tuple[HtmlNode, ...] = ()
    if card.description is not None or card.copy_to_clipboard:
        detail = (
            Span(
                card.description or "",
                **_copy_status_attributes(card, "utility-link__detail"),
            ),
        )
    return (
        Div(
            *detail,
            Span(card.title, cls="utility-link__title"),
            cls="utility-link__copy",
        ),
        _svg_icon(cls="utility-link__icon", frame_cls="utility-link__icon-frame"),
    )


def _card_anchor(card: LinkCard, *contents: HtmlNode) -> HtmlNode:
    attributes = {
        "href": card.href,
        "cls": "hub-card__link",
        "aria_label": f"Open {card.title}",
    }
    if card.copy_to_clipboard:
        attributes.update(_clipboard_link_attributes(card))
    attributes.update(_external_link_attributes(card))
    return A(*contents, **attributes)


def _clipboard_link_attributes(card: LinkCard) -> dict[str, str]:
    """Return accessible data attributes for a copy-and-follow link."""

    copy_text = card.clipboard_text
    return {
        "data_copy_text": copy_text,
        "aria_label": f"Copy {copy_text} to clipboard and open {card.title}",
    }


def _copy_status_attributes(card: LinkCard, cls: str) -> dict[str, str]:
    """Return description attributes, including accessible copy feedback when needed."""

    attributes = {"cls": cls}
    if card.copy_to_clipboard:
        attributes.update(data_copy_status="", aria_live="polite")
    return attributes


def _svg_icon(*, cls: str, frame_cls: str) -> HtmlNode:
    """Render a decorative SVG mask."""

    return Div(Span(aria_hidden="true", cls=cls), cls=frame_cls)


def _card_style(card: LinkCard) -> str:
    declarations = [
        f"--icon-scale: {card.icon_scale / 100:g}",
        f"--icon-source: url({dumps(card.icon)})",
    ]
    declarations.extend(
        f"{name}: {color}"
        for name, color in (
            ("--border-static", card.border_static),
            ("--border-hover", card.border_hover),
            ("--icon-static", card.icon_static),
            ("--icon-hover", card.icon_hover),
        )
        if color is not None
    )
    return "; ".join(declarations) + ";"


def _external_link_attributes(card: LinkCard) -> dict[str, str]:
    return (
        {}
        if not card.opens_in_new_tab
        else {"target": "_blank", "rel": "noopener noreferrer"}
    )
