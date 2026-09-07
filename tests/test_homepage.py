"""Public behavior checks for the single-page hub."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from unittest import TestCase
from unittest.mock import patch

import httpx

try:
    import uvloop
except ModuleNotFoundError:
    uvloop = None

from apasz_hub.app import STATIC_DIRECTORY, app
from apasz_hub.components import document_headers, link_card, utility_link
from apasz_hub.data import (
    FAVICON_URL,
    PROFILE_IMAGE_URL,
    PROFILE_REDUCED_MOTION_IMAGE_URL,
    SITE_SCRIPT_URL,
    WORDMARK_URL,
    CardKind,
    CardTier,
    load_link_cards,
)
from apasz_hub.framework import render
from apasz_hub.github import (
    GithubRepositoryCountCache,
    GithubRepositoryCountUnavailable,
)
from apasz_hub.middleware import SECURITY_HEADERS, STATIC_CACHE_CONTROL
from apasz_hub.pages import homepage


async def _application_responses() -> tuple[
    httpx.Response, httpx.Response, httpx.Response
]:
    with patch("apasz_hub.pages.GITHUB_REPOSITORY_COUNTS", _repository_count_cache()):
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport, base_url="http://testserver"
        ) as client:
            page_response = await client.get("/")
            stylesheet_response = await client.get("/static/site.css")
            cached_stylesheet_response = await client.get(
                "/static/site.css",
                headers={"If-None-Match": stylesheet_response.headers["etag"]},
            )
            return page_response, stylesheet_response, cached_stylesheet_response


def _run_application_responses() -> tuple[
    httpx.Response, httpx.Response, httpx.Response
]:
    """Exercise file responses on Uvicorn's available event loop."""

    if uvloop is None:
        return asyncio.run(_application_responses())
    return uvloop.run(_application_responses())


class HomepageTests(TestCase):
    """Keep the public page and its configuration coherent."""

    def test_homepage_renders_every_destination(self) -> None:
        document = render(asyncio.run(homepage(_repository_count_cache())))
        cards = load_link_cards()

        self.assertIn("APasz", document)
        self.assertIn(f"--wordmark-source: url({WORDMARK_URL})", document)
        self.assertIn(f'src="{PROFILE_IMAGE_URL}"', document)
        self.assertIn(f'srcset="{PROFILE_REDUCED_MOTION_IMAGE_URL}"', document)
        self.assertIn('media="(prefers-reduced-motion: reduce)"', document)
        self.assertIn("Critical Thinking is a Virtue", document)
        for card in cards:
            self.assertIn(card.href, document)
        self.assertIn('data-copy-text="mail@apasz.com"', document)
        self.assertIn('aria-current="page"', document)

    def test_icons_are_available_locally(self) -> None:
        icon_urls = [card.icon for card in load_link_cards()]
        icon_urls.extend(("/static/icons/gitlab.svg", "/static/icons/youtube.svg"))
        for icon_url in icon_urls:
            icon = STATIC_DIRECTORY / icon_url.removeprefix("/static/")
            self.assertTrue(icon.is_file(), msg=icon_url)

    def test_card_invariants(self) -> None:
        cards = load_link_cards()
        featured = next(card for card in cards if card.tier is CardTier.FEATURED)
        email = next(card for card in cards if card.copy_to_clipboard)

        self.assertEqual(email.clipboard_text, "mail@apasz.com")
        self.assertIs(email.schema, CardKind.MAIL)
        self.assertIs(featured.schema, CardKind.GITHUB)
        self.assertEqual(featured.github_login, "APasz")
        with self.assertRaises(ValueError):
            replace(featured, metadata=None)
        with self.assertRaises(ValueError):
            replace(featured, icon_scale=0)
        with self.assertRaises(ValueError):
            replace(featured, copy_to_clipboard=True)
        with self.assertRaises(ValueError):
            replace(email, schema=CardKind.NORMAL)
        with self.assertRaises(ValueError):
            replace(email, href="mailto:")
        with self.assertRaises(ValueError):
            replace(featured, href="https://github.com/APasz/homepage")
        with self.assertRaises(ValueError):
            replace(featured, href="https://github.com//APasz")

        copyable_featured = replace(
            featured,
            copy_to_clipboard=True,
            copy_text="https://example.com",
        )
        self.assertTrue(copyable_featured.opens_in_new_tab)
        self.assertEqual(copyable_featured.clipboard_text, "https://example.com")

    def test_homepage_replaces_github_metadata_with_the_repository_count(self) -> None:
        async def fetch_count(login: str) -> int:
            self.assertEqual(login, "apasz")
            return 30

        document = render(
            asyncio.run(homepage(GithubRepositoryCountCache(fetch_count)))
        )

        self.assertIn("30 Repositories", document)
        self.assertNotIn("29 Repositories", document)

    def test_cards_render_their_declared_presentation(self) -> None:
        cards = load_link_cards()
        card = replace(
            cards[0],
            icon_scale=150,
            border_hover="#1a2b3c",
            border_static="#4d5e6f",
            icon_static="#7a8b9c",
            icon_hover="#a1b2c3",
        )
        document = render(link_card(card))

        self.assertIn("--icon-scale: 1.5", document)
        self.assertIn('--icon-source: url("/static/icons/github.svg")', document)
        self.assertIn("--border-hover: #1a2b3c", document)
        self.assertIn("--border-static: #4d5e6f", document)
        self.assertIn("--icon-static: #7a8b9c", document)
        self.assertIn("--icon-hover: #a1b2c3", document)
        fallback_document = render(link_card(replace(cards[0], border_hover=None)))
        for variable in (
            "--border-static",
            "--border-hover",
            "--icon-static",
            "--icon-hover",
        ):
            self.assertNotIn(variable, fallback_document)
        self.assertIn('target="_blank"', document)
        self.assertIn('data-copy-status=""', render(utility_link(cards[-1])))
        copied_document = render(
            link_card(
                replace(
                    cards[0],
                    copy_to_clipboard=True,
                    copy_text="https://example.com",
                )
            )
        )
        self.assertIn('data-copy-text="https://example.com"', copied_document)
        self.assertIn('data-copy-status=""', copied_document)
        descriptionless_document = render(
            link_card(replace(cards[0], description=None))
        )
        self.assertNotIn('class="card__description"', descriptionless_document)

    def test_document_assets_are_linked(self) -> None:
        headers = render(*document_headers())
        stylesheet = (STATIC_DIRECTORY / "site.css").read_text(encoding="utf-8")
        script = (STATIC_DIRECTORY / "site.js").read_text(encoding="utf-8")

        self.assertIn(f'href="{FAVICON_URL}"', headers)
        self.assertIn(f'src="{SITE_SCRIPT_URL}"', headers)
        self.assertIn('href="/static/site.css"', headers)
        self.assertIn("mask-image", stylesheet)
        self.assertIn("var(--border-static, var(--border))", stylesheet)
        self.assertIn("var(--border-hover, var(--accent))", stylesheet)
        self.assertIn("var(--icon-static, var(--accent))", stylesheet)
        self.assertIn("var(--icon-hover, var(--accent))", stylesheet)
        self.assertIn("navigator.clipboard?.writeText", script)
        self.assertIn("event.preventDefault()", script)
        self.assertIn("window.location.assign(link.href)", script)
        self.assertTrue((STATIC_DIRECTORY / "media" / "pfp-anim.webp").is_file())
        self.assertTrue(
            (STATIC_DIRECTORY / WORDMARK_URL.removeprefix("/static/")).is_file()
        )
        self.assertIn("mask-image: var(--wordmark-source)", stylesheet)
        self.assertIn("translateY(var(--lockup-line-offset))", stylesheet)
        self.assertIn("--wordmark-height: clamp(3.6rem, 17.01vw, 4.95rem)", stylesheet)
        self.assertTrue((STATIC_DIRECTORY / "media" / "pfp-still.webp").is_file())

    def test_application_applies_response_policy(self) -> None:
        (
            page_response,
            stylesheet_response,
            cached_stylesheet_response,
        ) = _run_application_responses()

        self.assertEqual(page_response.status_code, 200)
        self.assertIn("APasz", page_response.text)
        for header, value in SECURITY_HEADERS:
            self.assertEqual(page_response.headers[header], value)
        self.assertNotIn("cache-control", page_response.headers)
        self.assertEqual(stylesheet_response.status_code, 200)
        self.assertEqual(
            stylesheet_response.headers["cache-control"],
            STATIC_CACHE_CONTROL,
        )
        self.assertEqual(cached_stylesheet_response.status_code, 304)
        self.assertEqual(
            cached_stylesheet_response.headers["cache-control"],
            STATIC_CACHE_CONTROL,
        )


async def _unavailable_repository_count(_: str) -> int:
    raise GithubRepositoryCountUnavailable("GitHub is unavailable in isolated tests.")


def _repository_count_cache() -> GithubRepositoryCountCache:
    return GithubRepositoryCountCache(_unavailable_repository_count)
