"""The public APasz hub page."""

from __future__ import annotations

from apasz_hub.components import link_card, utility_link
from apasz_hub.data import (
    PROFILE_IMAGE_URL,
    PROFILE_REDUCED_MOTION_IMAGE_URL,
    WORDMARK_URL,
    CardTier,
    LinkCard,
    cards_for_tier,
)
from apasz_hub.framework import (
    H1,
    Div,
    Header,
    HtmlNode,
    Img,
    Main,
    Nav,
    Picture,
    Section,
    Source,
    Span,
)
from apasz_hub.github import GithubRepositoryCountCache, enrich_github_metadata
from apasz_hub.routes.paths import SiteRoute

from .layout import site_footer


async def homepage(
    cards: tuple[LinkCard, ...],
    repository_counts: GithubRepositoryCountCache,
) -> HtmlNode:
    """Build the small, single-page public APasz hub."""

    enriched_cards = await enrich_github_metadata(cards, repository_counts)
    return Main(
        _header(),
        _card_section(enriched_cards, CardTier.FEATURED, "Primary links"),
        _card_section(enriched_cards, CardTier.STANDARD, "Other public links"),
        _utility_section(enriched_cards),
        site_footer(SiteRoute.HOME),
        cls="site-shell",
    )


def _header() -> HtmlNode:
    """Render the public profile and wordmark lockup."""

    return Header(
        Div(
            Picture(
                Source(
                    media="(prefers-reduced-motion: reduce)",
                    srcset=PROFILE_REDUCED_MOTION_IMAGE_URL,
                    type="image/webp",
                ),
                Img(
                    src=PROFILE_IMAGE_URL,
                    alt="",
                    aria_hidden="true",
                    cls="profile-image",
                ),
                cls="profile-image-frame",
            ),
            H1(
                Span("APasz", cls="wordmark__label"),
                cls="wordmark",
                style=f"--wordmark-source: url({WORDMARK_URL})",
            ),
            cls="wordmark-lockup",
        ),
        cls="site-header",
    )


def _card_section(cards: tuple[LinkCard, ...], tier: CardTier, label: str) -> HtmlNode:
    """Render one non-utility card tier as a labelled grid."""

    return Section(
        Div(
            *(link_card(card) for card in cards_for_tier(cards, tier)),
            cls=f"link-grid link-grid--{tier.value}",
        ),
        aria_label=label,
        cls="hub-section",
    )


def _utility_section(cards: tuple[LinkCard, ...]) -> HtmlNode:
    """Render compact utility destinations."""

    return Section(
        Nav(
            *(utility_link(card) for card in cards_for_tier(cards, CardTier.UTILITY)),
            aria_label="Utility links",
            cls="utility-grid",
        ),
        cls="hub-section hub-section--utilities",
    )
