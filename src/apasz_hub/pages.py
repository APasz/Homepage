"""Server-rendered page compositions for the APasz hub."""

from __future__ import annotations

from apasz_hub.components import link_card, utility_link
from apasz_hub.data import (
    PROFILE_IMAGE_URL,
    PROFILE_REDUCED_MOTION_IMAGE_URL,
    WORDMARK_URL,
    CardTier,
    LinkCard,
    cards_for_tier,
    load_link_cards,
)
from apasz_hub.framework import (
    H1,
    A,
    Div,
    Footer,
    Header,
    HtmlNode,
    Img,
    Li,
    Main,
    Nav,
    P,
    Picture,
    Section,
    Source,
    Span,
    Ul,
)
from apasz_hub.github import (
    GITHUB_REPOSITORY_COUNTS,
    GithubRepositoryCountCache,
    enrich_github_metadata,
)


async def homepage(
    repository_counts: GithubRepositoryCountCache | None = None,
) -> HtmlNode:
    """Build the small, single-page public APasz hub."""

    cards = load_link_cards()
    counts = (
        GITHUB_REPOSITORY_COUNTS if repository_counts is None else repository_counts
    )
    cards = await enrich_github_metadata(cards, counts)
    return Main(
        Header(
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
        ),
        _card_section(cards, CardTier.FEATURED, "Primary links"),
        _card_section(cards, CardTier.STANDARD, "Other public links"),
        Section(
            Nav(
                *(
                    utility_link(card)
                    for card in cards_for_tier(cards, CardTier.UTILITY)
                ),
                aria_label="Utility links",
                cls="utility-grid",
            ),
            cls="hub-section hub-section--utilities",
        ),
        Footer(
            Nav(
                Ul(
                    Li(A("Home", href="/", aria_current="page", cls="site-nav__link")),
                    cls="site-nav__list",
                ),
                aria_label="Site navigation",
                cls="site-nav",
            ),
            P("Critical Thinking is a Virtue", cls="signature"),
            cls="site-footer",
        ),
        cls="site-shell",
    )


def _card_section(cards: tuple[LinkCard, ...], tier: CardTier, label: str) -> HtmlNode:
    """Render a card tier as a labelled grid."""

    return Section(
        Div(
            *(link_card(card) for card in cards_for_tier(cards, tier)),
            cls=f"link-grid link-grid--{tier.value}",
        ),
        aria_label=label,
        cls="hub-section",
    )
