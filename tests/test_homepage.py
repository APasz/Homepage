"""Public behavior checks for the hub pages and their configuration."""

from __future__ import annotations

import asyncio
from base64 import urlsafe_b64encode
from collections.abc import Coroutine, Mapping
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Never
from unittest import TestCase
from unittest.mock import patch

import httpx
from starlette.exceptions import HTTPException

try:
    import uvloop
except ModuleNotFoundError:
    uvloop = None

from apasz_hub import config_security
from apasz_hub.app import app
from apasz_hub.application import STATIC_DIRECTORY, create_application
from apasz_hub.components import (
    document_headers,
    link_card,
    theme_color_meta,
    utility_link,
)
from apasz_hub.data import (
    DEFAULT_LINK_CARDS_PATH,
    FAVICON_URL,
    LINK_CARD_COLOUR_CONTROL_PAIRS,
    LINK_CARD_COLOUR_CONTROLS,
    LINK_CARD_DELETE_INDEX_FORM_NAME,
    PROFILE_IMAGE_URL,
    PROFILE_REDUCED_MOTION_IMAGE_URL,
    SITE,
    SITE_SCRIPT_URL,
    SITE_STYLESHEET_URL,
    WORDMARK_URL,
    CardKind,
    CardTier,
    LinkCardFormField,
    LinkCardStore,
    link_card_form_name,
    load_icon_assets,
    load_link_cards,
)
from apasz_hub.framework import FastHTMLApp, render
from apasz_hub.github import (
    GithubRepositoryCountCache,
    GithubRepositoryCountUnavailable,
)
from apasz_hub.middleware import (
    NO_STORE_CACHE_CONTROL,
    SECURITY_HEADERS,
    STATIC_CACHE_CONTROL,
)
from apasz_hub.open_graph import (
    DEFAULT_OPEN_GRAPH_PATH,
    OPEN_GRAPH_FIELD_DEFINITIONS,
    OpenGraphField,
    OpenGraphStore,
    load_open_graph_metadata,
)
from apasz_hub.pages import (
    ErrorPageStatus,
    configuration_login_page,
    configuration_page,
    error_page,
    homepage,
)
from apasz_hub.routes.configuration import LINK_CARD_DRAFT_REVISION_HEADER
from apasz_hub.routes.paths import SiteRoute
from apasz_hub.services import create_application_services
from apasz_hub.theme import (
    DEFAULT_THEME_COLORS_PATH,
    ERROR_COLOUR,
    THEME_STYLESHEET_CACHE_CONTROL,
    THEME_STYLESHEET_URL,
    ThemeColorStore,
    ThemeColorToken,
    load_theme_colors,
    theme_stylesheet,
)
from tests.link_card_form_data import link_card_form_values

CONFIG_TEST_ORIGIN = "https://testserver"
CONFIG_TEST_PASSWORD = "correct horse battery staple"
CONFIG_TEST_ENVIRONMENT = {
    config_security.CONFIG_PASSWORD_HASH_ENV: config_security.CONFIG_PASSWORD_HASHER.hash(
        CONFIG_TEST_PASSWORD
    ),
    config_security.CONFIG_SESSION_SECRET_ENV: urlsafe_b64encode(b"t" * 32)
    .decode()
    .rstrip("="),
    config_security.PUBLIC_ORIGIN_ENV: CONFIG_TEST_ORIGIN,
}


def _config_access() -> config_security.ConfigAccess:
    """Return isolated, HTTPS-only configuration authentication for one test."""

    return config_security.ConfigAccess(environment=CONFIG_TEST_ENVIRONMENT)


async def _authenticate_config_client(
    client: httpx.AsyncClient,
    access: config_security.ConfigAccess,
) -> str:
    """Log a test client in and return its CSRF token."""

    response = await client.post(
        SiteRoute.CONFIG_LOGIN.value,
        data={config_security.CONFIG_PASSWORD_FORM_NAME: CONFIG_TEST_PASSWORD},
        headers={"Origin": CONFIG_TEST_ORIGIN},
        follow_redirects=False,
    )
    if response.status_code != 303:
        raise AssertionError(f"Configuration login failed with {response.status_code}.")
    settings = access.settings()
    if settings is None:
        raise AssertionError("Test configuration access is unavailable.")
    session_id = client.cookies.get(
        config_security.configuration_session_cookie_name(settings),
    )
    session = access.authenticate(session_id)
    if session is None:
        raise AssertionError("Configuration login did not create a session.")
    return session.csrf_token


def _csrf_form_values(
    values: Mapping[str, object],
    csrf_token: str,
) -> dict[str, object]:
    """Add the configuration CSRF field to a submitted form snapshot."""

    return {**values, config_security.CONFIG_CSRF_FORM_NAME: csrf_token}


def _config_headers(csrf_token: str) -> dict[str, str]:
    """Return browser request metadata expected by protected config routes."""

    return {
        "Origin": CONFIG_TEST_ORIGIN,
        config_security.CONFIG_CSRF_HEADER: csrf_token,
    }


def _isolated_application(
    *,
    link_cards: LinkCardStore | None = None,
    theme_colors: ThemeColorStore | None = None,
    open_graph: OpenGraphStore | None = None,
    github_repository_counts: GithubRepositoryCountCache | None = None,
) -> FastHTMLApp:
    """Build an application whose mutable collaborators belong to one test."""

    return create_application(
        create_application_services(
            link_cards=link_cards,
            theme_colors=theme_colors,
            open_graph=open_graph,
            github_repository_counts=(
                _repository_count_cache()
                if github_repository_counts is None
                else github_repository_counts
            ),
        ),
    )


async def _application_responses(
    access: config_security.ConfigAccess,
) -> tuple[
    httpx.Response, httpx.Response, httpx.Response, httpx.Response, httpx.Response
]:
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport, base_url=CONFIG_TEST_ORIGIN
    ) as client:
        page_response = await client.get("/")
        stylesheet_response = await client.get(SITE_STYLESHEET_URL)
        cached_stylesheet_response = await client.get(
            SITE_STYLESHEET_URL,
            headers={"If-None-Match": stylesheet_response.headers["etag"]},
        )
        await _authenticate_config_client(client, access)
        config_response = await client.get("/config")
        theme_response = await client.get(THEME_STYLESHEET_URL)
        return (
            page_response,
            stylesheet_response,
            cached_stylesheet_response,
            config_response,
            theme_response,
        )


def _run_application_responses() -> tuple[
    httpx.Response, httpx.Response, httpx.Response, httpx.Response, httpx.Response
]:
    """Exercise file responses on Uvicorn's available event loop."""

    access = _config_access()
    with patch.object(config_security, "CONFIG_ACCESS", access):
        return _run_test_coroutine(_application_responses(access))


def _run_test_coroutine[Result](
    coroutine: Coroutine[object, object, Result],
) -> Result:
    """Run a test coroutine on the event loop available to Uvicorn."""

    if uvloop is None:
        return asyncio.run(coroutine)
    return uvloop.run(coroutine)


async def _get_responses(
    test_app: FastHTMLApp,
    *paths: str,
    raise_app_exceptions: bool = True,
) -> list[httpx.Response]:
    """Request public paths from one isolated ASGI application."""

    transport = httpx.ASGITransport(
        app=test_app,
        raise_app_exceptions=raise_app_exceptions,
    )
    async with httpx.AsyncClient(
        transport=transport,
        base_url=CONFIG_TEST_ORIGIN,
    ) as client:
        return [await client.get(path) for path in paths]


class HomepageTests(TestCase):
    """Keep the public page and its configuration coherent."""

    def test_homepage_renders_every_destination(self) -> None:
        cards = load_link_cards()
        document = render(asyncio.run(homepage(cards, _repository_count_cache())))

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
        self.assertNotIn('href="/config"', document)

    def test_configuration_page_renders_editable_controls(self) -> None:
        colors = load_theme_colors()
        cards = load_link_cards()
        icon_assets = load_icon_assets()
        document = render(
            configuration_page(
                colors,
                cards,
                icon_assets,
                csrf_token="test-csrf-token",
            )
        )

        self.assertIn("Configuration", document)
        self.assertIn('class="site-shell"', document)
        self.assertNotIn("config-shell", document)
        self.assertIn("Link cards", document)
        self.assertIn('aria-label="Link card management"', document)
        self.assertEqual(document.count("<details"), len(cards))
        self.assertEqual(document.count("<summary"), len(cards))
        self.assertIn('data-link-card-controls=""', document)
        self.assertIn('data-link-card-draft-url="/config/link-cards/draft"', document)
        self.assertIn('data-link-card-draft-revision="0"', document)
        self.assertIn('action="/config/link-cards"', document)
        self.assertIn('formaction="/config/link-cards/add"', document)
        self.assertIn('formaction="/config/link-cards/delete"', document)
        self.assertIn("Add Link", document)
        self.assertIn("Save Links", document)
        self.assertEqual(document.count('data-link-card-delete=""'), len(cards))
        self.assertEqual(document.count('formnovalidate=""'), len(cards))
        for card in cards:
            self.assertIn(card.title, document)
        for index, card in enumerate(cards):
            self.assertIn(
                f'name="{link_card_form_name(index, LinkCardFormField.TITLE)}"',
                document,
            )
            self.assertIn(
                f'value="{card.title}"',
                document,
            )
            self.assertIn(
                f'name="{link_card_form_name(index, LinkCardFormField.DESTINATION)}"',
                document,
            )
        first_schema_name = link_card_form_name(0, LinkCardFormField.SCHEMA)
        first_destination_name = link_card_form_name(0, LinkCardFormField.DESTINATION)
        self.assertLess(
            document.index(f'name="{first_schema_name}"'),
            document.index(f'name="{first_destination_name}"'),
        )
        self.assertIn('data-link-card-destination-schema="github"', document)
        self.assertIn('data-link-card-destination-schema="mail"', document)
        self.assertIn('value="APasz"', document)
        self.assertIn('value="mail@apasz.com"', document)
        self.assertNotIn('value="mailto:mail@apasz.com"', document)
        self.assertIn('data-icon-picker-dialog=""', document)
        self.assertEqual(
            document.count('data-icon-picker-trigger=""'),
            len(cards),
        )
        self.assertEqual(
            document.count("data-icon-picker-option="),
            len(icon_assets),
        )
        for icon in icon_assets:
            self.assertIn(f'data-icon-picker-option="{icon.url}"', document)
            self.assertIn(f'src="{icon.url}"', document)
            self.assertIn(icon.name, document)
        self.assertEqual(
            document.count('data-link-card-colour-control=""'),
            len(cards) * len(LINK_CARD_COLOUR_CONTROLS),
        )
        self.assertEqual(
            document.count('class="link-card-colour-pair__controls"'),
            len(cards) * len(LINK_CARD_COLOUR_CONTROL_PAIRS),
        )
        self.assertEqual(document.count(">Border static / hover<"), len(cards))
        self.assertEqual(document.count(">Icon static / hover<"), len(cards))
        self.assertEqual(
            document.count('class="link-card-toggle-pair"'),
            len(cards),
        )
        for index in range(len(cards)):
            for control in LINK_CARD_COLOUR_CONTROLS:
                self.assertIn(
                    f'name="{link_card_form_name(index, control.field)}"',
                    document,
                )
                self.assertIn(
                    f'name="{link_card_form_name(index, control.auto_field)}"',
                    document,
                )
                self.assertIn(
                    f'data-link-card-colour-fallback="{control.fallback_token.value}"',
                    document,
                )
        self.assertIn("Site colours", document)
        self.assertIn('data-theme-controls=""', document)
        self.assertIn('data-theme-reset=""', document)
        self.assertIn('action="/config/colours"', document)
        self.assertIn('action="/config/logout"', document)
        self.assertIn('name="config-csrf-token" value="test-csrf-token"', document)
        self.assertIn('enctype="application/x-www-form-urlencoded"', document)
        self.assertIn('type="submit"', document)
        self.assertIn("Save colours", document)
        self.assertIn("Open Graph", document)
        self.assertIn('aria-label="Open Graph configuration"', document)
        self.assertIn('action="/config/open-graph"', document)
        self.assertIn("Save Open Graph", document)
        for definition in OPEN_GRAPH_FIELD_DEFINITIONS:
            self.assertIn(f'name="{definition.field.value}"', document)
            self.assertIn(
                f'maxlength="{definition.maximum_length}"',
                document,
            )
        self.assertNotIn('href="/config"', document)
        self.assertNotIn('data-theme-color="github"', document)
        self.assertNotIn("Button styles", document)
        self.assertNotIn("button-showcase", document)
        for color in colors:
            self.assertIn(
                f'data-theme-color="{color.token.value}"',
                document,
            )
            self.assertIn(f'name="{color.token.value}"', document)
            self.assertIn(f'value="{color.value}"', document)

    def test_configuration_login_does_not_mislabel_home_as_the_current_page(
        self,
    ) -> None:
        document = render(configuration_login_page())

        self.assertIn('action="/config/login"', document)
        self.assertNotIn('aria-current="page"', document)

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
        self.assertEqual(featured.border_hover, "#f0f6fc")
        with self.assertRaises(ValueError):
            replace(featured, metadata=None)
        with self.assertRaises(ValueError):
            replace(featured, icon_scale=0)
        with self.assertRaises(ValueError):
            replace(featured, icon_scale=True)
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
        with self.assertRaises(ValueError):
            replace(featured, border_hover="purple")

        copyable_featured = replace(
            featured,
            copy_to_clipboard=True,
            copy_text="https://example.com",
        )
        self.assertTrue(copyable_featured.opens_in_new_tab)
        self.assertEqual(copyable_featured.clipboard_text, "https://example.com")

    def test_homepage_replaces_github_metadata_with_the_repository_count(self) -> None:
        fallback_metadata = _github_fallback_metadata()
        repository_count = 30 if fallback_metadata != "30 Repositories" else 31
        expected_metadata = f"{repository_count} Repositories"

        async def fetch_count(login: str) -> int:
            self.assertEqual(login, "apasz")
            return repository_count

        cache = GithubRepositoryCountCache(fetch_count)
        asyncio.run(cache.refresh("APasz"))
        document = render(asyncio.run(homepage(load_link_cards(), cache)))

        self.assertIn(expected_metadata, document)
        self.assertNotIn(fallback_metadata, document)

    def test_homepage_does_not_trigger_a_github_refresh(self) -> None:
        calls: list[str] = []
        fallback_metadata = _github_fallback_metadata()

        async def fetch_count(login: str) -> int:
            calls.append(login)
            return 30

        document = render(
            asyncio.run(
                homepage(load_link_cards(), GithubRepositoryCountCache(fetch_count))
            )
        )

        self.assertIn(fallback_metadata, document)
        self.assertEqual(calls, [])

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
        colors = load_theme_colors()
        headers = render(*document_headers())
        browser_theme_meta = render(theme_color_meta(colors))
        stylesheet = (STATIC_DIRECTORY / "site.css").read_text(encoding="utf-8")
        script = (STATIC_DIRECTORY / "site.js").read_text(encoding="utf-8")

        self.assertIn(f'href="{FAVICON_URL}"', headers)
        self.assertIn(f'src="{SITE_SCRIPT_URL}"', headers)
        self.assertIn(f'href="{THEME_STYLESHEET_URL}"', headers)
        self.assertIn(f'href="{SITE_STYLESHEET_URL}"', headers)
        self.assertLess(
            headers.index('<meta charset="utf-8">'),
            headers.index("<title>APasz</title>"),
        )
        self.assertLess(
            headers.index(f'href="{THEME_STYLESHEET_URL}"'),
            headers.index(f'href="{SITE_STYLESHEET_URL}"'),
        )
        self.assertRegex(SITE_STYLESHEET_URL, r"^/static/site\.css\?v=[0-9a-f]{12}$")
        self.assertRegex(SITE_SCRIPT_URL, r"^/static/site\.js\?v=[0-9a-f]{12}$")
        self.assertNotIn('data-theme-color-token="canvas"', headers)
        self.assertIn('data-theme-color-token="canvas"', browser_theme_meta)
        self.assertIn("mask-image", stylesheet)
        self.assertIn("scrollbar-gutter: stable both-edges;", stylesheet)
        self.assertIn("var(--border-static, var(--color-border))", stylesheet)
        self.assertIn("var(--border-hover, var(--color-accent))", stylesheet)
        self.assertIn("var(--icon-static, var(--color-accent))", stylesheet)
        self.assertIn("var(--icon-hover, var(--color-accent))", stylesheet)
        self.assertIn(
            ".link-card-colour-control__input::-webkit-color-swatch {",
            stylesheet,
        )
        self.assertIn(
            ".link-card-colour-control__input::-moz-color-swatch {",
            stylesheet,
        )
        self.assertNotRegex(stylesheet, r"#[0-9A-Fa-f]{3,8}\b")
        for color in colors:
            self.assertIn(
                f"{color.css_variable}: {color.value};",
                theme_stylesheet(colors),
            )
        shadow = next(
            color for color in colors if color.token is ThemeColorToken.SHADOW
        )
        shadow_channels = " ".join(
            str(int(shadow.value[index : index + 2], 16)) for index in (1, 3, 5)
        )
        self.assertIn("--shadow-opacity: 34%;", stylesheet)
        self.assertIn("background: var(--color-error);", stylesheet)
        self.assertIn(
            f"--color-error: {ERROR_COLOUR};",
            theme_stylesheet(colors),
        )
        self.assertIn(
            f"--shadow: rgb({shadow_channels} / var(--shadow-opacity));",
            theme_stylesheet(colors),
        )
        self.assertNotIn("rgb(from", theme_stylesheet(colors))
        self.assertIn("navigator.clipboard?.writeText", script)
        self.assertIn("event.preventDefault()", script)
        self.assertIn("window.location.assign(link.href)", script)
        self.assertIn("Unsaved changes.", script)
        self.assertIn("form.reset()", script)
        self.assertIn('input.addEventListener("change"', script)
        self.assertIn("function shadowCssValue", script)
        self.assertIn("data-theme-color", script)
        self.assertIn("function configureLinkCardControls", script)
        self.assertIn("function configureColourControls", script)
        self.assertIn("function updateAutomaticLinkCardColours", script)
        self.assertIn("Draft updated. Save Links to publish.", script)
        self.assertIn("data-link-card-delete", script)
        self.assertIn(
            ".link-card-manager__card[open] .link-card-manager__delete",
            stylesheet,
        )
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
            config_response,
            theme_response,
        ) = _run_application_responses()

        self.assertEqual(page_response.status_code, 200)
        self.assertIn("APasz", page_response.text)
        canvas = next(
            color.value
            for color in load_theme_colors()
            if color.token is ThemeColorToken.CANVAS
        )
        self.assertIn(
            f'<meta name="theme-color" content="{canvas}"',
            page_response.text,
        )
        for header, value in SECURITY_HEADERS:
            self.assertEqual(page_response.headers[header], value)
        self.assertIn(
            "form-action 'self'", page_response.headers["content-security-policy"]
        )
        self.assertIn(
            "connect-src 'self'", page_response.headers["content-security-policy"]
        )
        self.assertEqual(
            page_response.headers["cache-control"],
            NO_STORE_CACHE_CONTROL,
        )
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
        self.assertEqual(config_response.status_code, 200)
        self.assertEqual(
            config_response.headers["cache-control"],
            NO_STORE_CACHE_CONTROL,
        )
        self.assertIn('data-theme-controls=""', config_response.text)
        self.assertIn('data-link-card-controls=""', config_response.text)
        self.assertEqual(theme_response.status_code, 200)
        self.assertEqual(
            theme_response.text,
            theme_stylesheet(load_theme_colors()),
        )
        self.assertTrue(theme_response.headers["content-type"].startswith("text/css"))
        self.assertEqual(
            theme_response.headers["cache-control"],
            THEME_STYLESHEET_CACHE_CONTROL,
        )

    def test_health_check_reports_application_liveness(self) -> None:
        (response,) = _run_test_coroutine(
            _get_responses(_isolated_application(), SiteRoute.HEALTHZ.value)
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.text, "ok")
        self.assertTrue(response.headers["content-type"].startswith("text/plain"))
        self.assertEqual(response.headers["cache-control"], NO_STORE_CACHE_CONTROL)

    def test_not_found_response_uses_the_public_error_page(self) -> None:
        (response,) = _run_test_coroutine(
            _get_responses(_isolated_application(), "/missing-page")
        )

        self.assertEqual(response.status_code, ErrorPageStatus.NOT_FOUND.value)
        self.assertIn("Page not found", response.text)
        self.assertIn('class="error-page__panel"', response.text)
        self.assertIn('href="/"', response.text)
        self.assertNotIn("404 Not Found", response.text)
        self.assertEqual(response.headers["cache-control"], NO_STORE_CACHE_CONTROL)
        for header, value in SECURITY_HEADERS:
            self.assertEqual(response.headers[header], value)

    def test_error_pages_are_available_at_their_canonical_paths(self) -> None:
        not_found_response, server_error_response = _run_test_coroutine(
            _get_responses(
                _isolated_application(),
                SiteRoute.NOT_FOUND.value,
                SiteRoute.INTERNAL_SERVER_ERROR.value,
            )
        )

        expected_responses = (
            (
                not_found_response,
                ErrorPageStatus.NOT_FOUND,
                "Page not found",
            ),
            (
                server_error_response,
                ErrorPageStatus.INTERNAL_SERVER_ERROR,
                "Something went wrong",
            ),
        )
        for response, status, heading in expected_responses:
            self.assertEqual(response.status_code, status.value)
            self.assertIn(heading, response.text)
            self.assertIn(
                f"<title>{status.value} · {SITE.title}</title>",
                response.text,
            )
            self.assertEqual(response.headers["cache-control"], NO_STORE_CACHE_CONTROL)
            for header, value in SECURITY_HEADERS:
                self.assertEqual(response.headers[header], value)

    def test_error_response_handlers_use_the_public_error_page(self) -> None:
        async def broken_endpoint() -> Never:
            raise RuntimeError("Intentional error page test failure.")

        async def declared_error_endpoint() -> Never:
            raise HTTPException(
                status_code=ErrorPageStatus.INTERNAL_SERVER_ERROR.value,
                detail="Intentional declared error page test failure.",
                headers={"Retry-After": "60"},
            )

        async def declared_not_found_endpoint() -> Never:
            raise HTTPException(
                status_code=ErrorPageStatus.NOT_FOUND.value,
                detail="Intentional declared not-found page test failure.",
                headers={"X-Error-Source": "declared"},
            )

        test_app = _isolated_application()
        test_app.get("/error-page-test")(broken_endpoint)
        test_app.get("/declared-error-page-test")(declared_error_endpoint)
        test_app.get("/declared-not-found-page-test")(declared_not_found_endpoint)
        responses = _run_test_coroutine(
            _get_responses(
                test_app,
                "/error-page-test",
                "/declared-error-page-test",
                "/declared-not-found-page-test",
                raise_app_exceptions=False,
            )
        )

        expected_responses = (
            (
                responses[0],
                ErrorPageStatus.INTERNAL_SERVER_ERROR,
                "Something went wrong",
            ),
            (
                responses[1],
                ErrorPageStatus.INTERNAL_SERVER_ERROR,
                "Something went wrong",
            ),
            (
                responses[2],
                ErrorPageStatus.NOT_FOUND,
                "Page not found",
            ),
        )
        for response, status, heading in expected_responses:
            self.assertEqual(response.status_code, status.value)
            self.assertIn(heading, response.text)
            self.assertIn('class="error-page__panel"', response.text)
            self.assertEqual(response.headers["cache-control"], NO_STORE_CACHE_CONTROL)
            for header, value in SECURITY_HEADERS:
                self.assertEqual(response.headers[header], value)
        self.assertNotIn("Intentional error page test failure.", responses[0].text)
        self.assertNotIn(
            "Intentional declared error page test failure.",
            responses[1].text,
        )
        self.assertEqual(responses[1].headers["retry-after"], "60")
        self.assertNotIn(
            "Intentional declared not-found page test failure.",
            responses[2].text,
        )
        self.assertEqual(responses[2].headers["x-error-source"], "declared")

    def test_error_page_copy_and_statuses_are_explicit(self) -> None:
        not_found_document = render(*error_page(ErrorPageStatus.NOT_FOUND))
        server_error_document = render(
            *error_page(ErrorPageStatus.INTERNAL_SERVER_ERROR)
        )

        self.assertIn(f"404 · {SITE.title}", not_found_document)
        self.assertIn("Not found", not_found_document)
        self.assertIn(f"500 · {SITE.title}", server_error_document)
        self.assertIn("Server error", server_error_document)
        self.assertIn("Back to home", server_error_document)

    def test_malformed_manual_theme_edit_keeps_public_responses_available(
        self,
    ) -> None:
        async def public_responses(
            test_app: FastHTMLApp,
        ) -> tuple[httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=test_app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=CONFIG_TEST_ORIGIN,
            ) as client:
                return (
                    await client.get(SiteRoute.HOME.value),
                    await client.get(THEME_STYLESHEET_URL),
                )

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "theme_colors.json"
            path.write_text(
                DEFAULT_THEME_COLORS_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            store = ThemeColorStore(path)
            published_colors = store.load()
            path.write_text("{not valid JSON", encoding="utf-8")

            with (
                patch("apasz_hub.theme.load_theme_colors") as load_colors,
            ):
                page_response, theme_response = asyncio.run(
                    public_responses(_isolated_application(theme_colors=store)),
                )

        load_colors.assert_not_called()
        canvas = next(
            color.value
            for color in published_colors
            if color.token is ThemeColorToken.CANVAS
        )
        self.assertEqual(page_response.status_code, 200)
        self.assertIn(
            f'<meta name="theme-color" content="{canvas}"',
            page_response.text,
        )
        self.assertEqual(theme_response.status_code, 200)
        self.assertEqual(theme_response.text, theme_stylesheet(published_colors))

    def test_link_card_draft_stays_in_memory_until_saved(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            original_document = DEFAULT_LINK_CARDS_PATH.read_text(encoding="utf-8")
            path.write_text(original_document, encoding="utf-8")
            store = LinkCardStore(path)
            store.load()
            original_title = store.published_cards()[0].title
            draft_title = f"Draft {original_title}"
            draft_revision = store.draft_revision
            values = link_card_form_values(store.draft_cards())
            values[link_card_form_name(0, LinkCardFormField.TITLE)] = draft_title

            async def update_and_save(
                test_app: FastHTMLApp,
                access: config_security.ConfigAccess,
            ) -> tuple[
                httpx.Response,
                str,
                httpx.Response,
                httpx.Response,
                httpx.Response,
                httpx.Response,
                httpx.Response,
            ]:
                transport = httpx.ASGITransport(app=test_app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=CONFIG_TEST_ORIGIN,
                ) as client:
                    csrf_token = await _authenticate_config_client(client, access)
                    request_values = _csrf_form_values(values, csrf_token)
                    draft_response = await client.post(
                        SiteRoute.CONFIG_LINK_CARDS_DRAFT.value,
                        data=request_values,
                        headers={
                            **_config_headers(csrf_token),
                            LINK_CARD_DRAFT_REVISION_HEADER: str(draft_revision),
                        },
                    )
                    draft_document = path.read_text(encoding="utf-8")
                    published_before_save = await client.get("/")
                    config_draft = await client.get("/config")
                    save_response = await client.post(
                        SiteRoute.CONFIG_LINK_CARDS_SAVE.value,
                        data=request_values,
                        headers=_config_headers(csrf_token),
                        follow_redirects=False,
                    )
                    saved_config = await client.get(save_response.headers["location"])
                    published_after_save = await client.get("/")
                    return (
                        draft_response,
                        draft_document,
                        published_before_save,
                        config_draft,
                        save_response,
                        saved_config,
                        published_after_save,
                    )

            access = _config_access()
            test_app = _isolated_application(link_cards=store)
            with patch.object(config_security, "CONFIG_ACCESS", access):
                (
                    draft_response,
                    draft_document,
                    published_before_save,
                    config_draft,
                    save_response,
                    saved_config,
                    published_after_save,
                ) = asyncio.run(update_and_save(test_app, access))
            saved_cards = load_link_cards(path)

        self.assertEqual(draft_response.status_code, 204)
        self.assertEqual(draft_response.headers["cache-control"], "no-store")
        self.assertEqual(draft_response.headers["x-link-card-draft-revision"], "2")
        self.assertEqual(draft_document, original_document)
        self.assertIn(original_title, published_before_save.text)
        self.assertNotIn(draft_title, published_before_save.text)
        self.assertIn(draft_title, config_draft.text)
        self.assertIn("Draft changes", config_draft.text)
        self.assertEqual(save_response.status_code, 303)
        self.assertEqual(
            save_response.headers["location"],
            f"{SiteRoute.CONFIG.value}?link_cards_saved=1",
        )
        self.assertIn("Link cards saved", saved_config.text)
        self.assertIn(draft_title, published_after_save.text)
        self.assertEqual(saved_cards[0].title, draft_title)
        self.assertFalse(store.is_draft_dirty)

    def test_publishing_link_cards_refreshes_current_github_cards_in_background(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            path.write_text(
                DEFAULT_LINK_CARDS_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            store = LinkCardStore(path)
            cards = store.load()
            github_index = next(
                index
                for index, card in enumerate(cards)
                if card.schema is CardKind.GITHUB
            )
            values = link_card_form_values(cards)
            values[
                link_card_form_name(
                    github_index,
                    LinkCardFormField.DESTINATION,
                )
            ] = "octocat"
            calls: list[str] = []
            refresh_started = asyncio.Event()
            release_refresh = asyncio.Event()
            refresh_finished = asyncio.Event()

            async def fetch_count(login: str) -> int:
                calls.append(login)
                refresh_started.set()
                await release_refresh.wait()
                refresh_finished.set()
                return 42

            async def publish_and_render(
                test_app: FastHTMLApp,
                access: config_security.ConfigAccess,
            ) -> tuple[httpx.Response, httpx.Response]:
                transport = httpx.ASGITransport(app=test_app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=CONFIG_TEST_ORIGIN,
                ) as client:
                    csrf_token = await _authenticate_config_client(client, access)
                    save_response = await client.post(
                        SiteRoute.CONFIG_LINK_CARDS_SAVE.value,
                        data=_csrf_form_values(values, csrf_token),
                        headers=_config_headers(csrf_token),
                        follow_redirects=False,
                    )
                    await asyncio.wait_for(refresh_started.wait(), timeout=1)
                    release_refresh.set()
                    await asyncio.wait_for(refresh_finished.wait(), timeout=1)
                    return save_response, await client.get(SiteRoute.HOME.value)

            access = _config_access()
            test_app = _isolated_application(
                link_cards=store,
                github_repository_counts=GithubRepositoryCountCache(fetch_count),
            )
            with patch.object(config_security, "CONFIG_ACCESS", access):
                save_response, homepage_response = asyncio.run(
                    publish_and_render(test_app, access),
                )

        self.assertEqual(save_response.status_code, 303)
        self.assertEqual(calls, ["octocat"])
        self.assertEqual(store.published_cards()[github_index].github_login, "octocat")
        self.assertIn("42 Repositories", homepage_response.text)

    def test_failed_publish_refresh_keeps_configured_github_metadata(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            path.write_text(
                DEFAULT_LINK_CARDS_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            store = LinkCardStore(path)
            cards = store.load()
            github_index = next(
                index
                for index, card in enumerate(cards)
                if card.schema is CardKind.GITHUB
            )
            configured_metadata = "Configured fallback metadata"
            values = link_card_form_values(cards)
            values[link_card_form_name(github_index, LinkCardFormField.METADATA)] = (
                configured_metadata
            )
            refresh_attempted = asyncio.Event()
            calls: list[str] = []

            async def fetch_count(login: str) -> int:
                calls.append(login)
                refresh_attempted.set()
                raise GithubRepositoryCountUnavailable("GitHub is unavailable.")

            async def publish_and_render(
                test_app: FastHTMLApp,
                access: config_security.ConfigAccess,
            ) -> tuple[httpx.Response, httpx.Response]:
                transport = httpx.ASGITransport(app=test_app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=CONFIG_TEST_ORIGIN,
                ) as client:
                    csrf_token = await _authenticate_config_client(client, access)
                    save_response = await client.post(
                        SiteRoute.CONFIG_LINK_CARDS_SAVE.value,
                        data=_csrf_form_values(values, csrf_token),
                        headers=_config_headers(csrf_token),
                        follow_redirects=False,
                    )
                    await asyncio.wait_for(refresh_attempted.wait(), timeout=1)
                    return save_response, await client.get(SiteRoute.HOME.value)

            access = _config_access()
            test_app = _isolated_application(
                link_cards=store,
                github_repository_counts=GithubRepositoryCountCache(fetch_count),
            )
            with patch.object(config_security, "CONFIG_ACCESS", access):
                save_response, homepage_response = asyncio.run(
                    publish_and_render(test_app, access),
                )

        self.assertEqual(save_response.status_code, 303)
        self.assertEqual(calls, ["apasz"])
        self.assertEqual(
            store.published_cards()[github_index].metadata,
            configured_metadata,
        )
        self.assertIn(configured_metadata, homepage_response.text)

    def test_add_link_card_adds_an_unpublished_draft_entry(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            original_document = DEFAULT_LINK_CARDS_PATH.read_text(encoding="utf-8")
            path.write_text(original_document, encoding="utf-8")
            store = LinkCardStore(path)
            store.load()
            original_cards = store.draft_cards()
            values = link_card_form_values(original_cards)
            updated_title = "Updated first link"
            values[link_card_form_name(0, LinkCardFormField.TITLE)] = updated_title

            async def add_link_card(
                test_app: FastHTMLApp,
                access: config_security.ConfigAccess,
            ) -> tuple[httpx.Response, httpx.Response]:
                transport = httpx.ASGITransport(app=test_app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=CONFIG_TEST_ORIGIN,
                ) as client:
                    csrf_token = await _authenticate_config_client(client, access)
                    add_response = await client.post(
                        SiteRoute.CONFIG_LINK_CARDS_ADD.value,
                        data=_csrf_form_values(values, csrf_token),
                        headers=_config_headers(csrf_token),
                        follow_redirects=False,
                    )
                    config_response = await client.get(add_response.headers["location"])
                    return add_response, config_response

            access = _config_access()
            test_app = _isolated_application(link_cards=store)
            with patch.object(config_security, "CONFIG_ACCESS", access):
                add_response, config_response = asyncio.run(
                    add_link_card(test_app, access),
                )
            draft_document = path.read_text(encoding="utf-8")

        self.assertEqual(add_response.status_code, 303)
        self.assertEqual(add_response.headers["location"], SiteRoute.CONFIG.value)
        self.assertEqual(len(store.draft_cards()), len(original_cards) + 1)
        self.assertEqual(store.draft_cards()[0].title, updated_title)
        self.assertEqual(store.draft_cards()[-1].title, "New Link")
        self.assertEqual(store.published_cards(), original_cards)
        self.assertEqual(draft_document, original_document)
        self.assertIn(updated_title, config_response.text)
        self.assertIn("New Link", config_response.text)
        self.assertIn("Draft changes", config_response.text)

    def test_delete_link_card_removes_an_unpublished_draft_entry(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            original_document = DEFAULT_LINK_CARDS_PATH.read_text(encoding="utf-8")
            path.write_text(original_document, encoding="utf-8")
            store = LinkCardStore(path)
            store.load()
            original_cards = store.draft_cards()
            values = link_card_form_values(original_cards)
            updated_title = "Updated first link"
            values[link_card_form_name(0, LinkCardFormField.TITLE)] = updated_title
            values[link_card_form_name(1, LinkCardFormField.DESTINATION)] = ""
            values[LINK_CARD_DELETE_INDEX_FORM_NAME] = "1"

            async def delete_link_card(
                test_app: FastHTMLApp,
                access: config_security.ConfigAccess,
            ) -> tuple[httpx.Response, httpx.Response]:
                transport = httpx.ASGITransport(app=test_app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=CONFIG_TEST_ORIGIN,
                ) as client:
                    csrf_token = await _authenticate_config_client(client, access)
                    delete_response = await client.post(
                        SiteRoute.CONFIG_LINK_CARDS_DELETE.value,
                        data=_csrf_form_values(values, csrf_token),
                        headers=_config_headers(csrf_token),
                        follow_redirects=False,
                    )
                    config_response = await client.get(
                        delete_response.headers["location"]
                    )
                    return delete_response, config_response

            access = _config_access()
            test_app = _isolated_application(link_cards=store)
            with patch.object(config_security, "CONFIG_ACCESS", access):
                delete_response, config_response = asyncio.run(
                    delete_link_card(test_app, access),
                )
            draft_document = path.read_text(encoding="utf-8")

        self.assertEqual(delete_response.status_code, 303)
        self.assertEqual(delete_response.headers["location"], SiteRoute.CONFIG.value)
        self.assertEqual(len(store.draft_cards()), len(original_cards) - 1)
        self.assertEqual(store.draft_cards()[0].title, updated_title)
        self.assertEqual(store.draft_cards()[1:], original_cards[2:])
        self.assertEqual(store.published_cards(), original_cards)
        self.assertEqual(draft_document, original_document)
        self.assertIn(updated_title, config_response.text)
        self.assertNotIn(original_cards[1].title, config_response.text)
        self.assertIn("Draft changes", config_response.text)

    def test_link_card_draft_rejects_invalid_submission_without_mutating_state(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            original_document = DEFAULT_LINK_CARDS_PATH.read_text(encoding="utf-8")
            path.write_text(original_document, encoding="utf-8")
            store = LinkCardStore(path)
            store.load()
            original_title = store.draft_cards()[0].title
            values = link_card_form_values(store.draft_cards())
            values[link_card_form_name(0, LinkCardFormField.TITLE)] = ""

            async def submit_invalid_draft(
                test_app: FastHTMLApp,
                access: config_security.ConfigAccess,
            ) -> httpx.Response:
                transport = httpx.ASGITransport(app=test_app)
                async with httpx.AsyncClient(
                    transport=transport,
                    base_url=CONFIG_TEST_ORIGIN,
                ) as client:
                    csrf_token = await _authenticate_config_client(client, access)
                    return await client.post(
                        SiteRoute.CONFIG_LINK_CARDS_DRAFT.value,
                        data=_csrf_form_values(values, csrf_token),
                        headers=_config_headers(csrf_token),
                    )

            access = _config_access()
            test_app = _isolated_application(link_cards=store)
            with patch.object(config_security, "CONFIG_ACCESS", access):
                response = asyncio.run(submit_invalid_draft(test_app, access))
            saved_document = path.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(store.draft_cards()[0].title, original_title)
        self.assertEqual(store.published_cards()[0].title, original_title)
        self.assertEqual(saved_document, original_document)

    def test_configuration_save_persists_the_palette_json(self) -> None:
        values = {color.token.value: color.value for color in load_theme_colors()}
        values[ThemeColorToken.CANVAS.value] = "#123456"

        async def save_palette(
            test_app: FastHTMLApp,
            access: config_security.ConfigAccess,
        ) -> tuple[httpx.Response, httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=test_app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=CONFIG_TEST_ORIGIN,
            ) as client:
                csrf_token = await _authenticate_config_client(client, access)
                save_response = await client.post(
                    SiteRoute.CONFIG_COLOURS_SAVE.value,
                    data=_csrf_form_values(values, csrf_token),
                    headers=_config_headers(csrf_token),
                    follow_redirects=False,
                )
                config_response = await client.get(save_response.headers["location"])
                theme_response = await client.get(THEME_STYLESHEET_URL)
                return save_response, config_response, theme_response

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "theme_colors.json"
            path.write_text(
                DEFAULT_THEME_COLORS_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            store = ThemeColorStore(path)
            published_colors = store.load()
            access = _config_access()
            test_app = _isolated_application(theme_colors=store)
            with patch.object(config_security, "CONFIG_ACCESS", access):
                save_response, config_response, theme_response = asyncio.run(
                    save_palette(test_app, access),
                )
            saved_colors = load_theme_colors(path)

        self.assertEqual(save_response.status_code, 303)
        self.assertEqual(
            save_response.headers["location"],
            f"{SiteRoute.CONFIG.value}?saved=1",
        )
        self.assertIn('value="#123456"', config_response.text)
        self.assertIn('meta name="theme-color" content="#123456"', config_response.text)
        self.assertIn("Colours saved", config_response.text)
        self.assertIn("--color-canvas: #123456;", theme_response.text)
        self.assertNotEqual(store.published_colors(), published_colors)
        self.assertEqual(store.published_colors(), saved_colors)
        self.assertEqual(
            next(
                color.value
                for color in saved_colors
                if color.token is ThemeColorToken.CANVAS
            ),
            "#123456",
        )

    def test_configuration_save_rejects_invalid_colours_without_writing(self) -> None:
        values = {color.token.value: color.value for color in load_theme_colors()}
        values[ThemeColorToken.ACCENT.value] = "purple"

        async def save_palette(
            test_app: FastHTMLApp,
            access: config_security.ConfigAccess,
        ) -> httpx.Response:
            transport = httpx.ASGITransport(app=test_app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=CONFIG_TEST_ORIGIN,
            ) as client:
                csrf_token = await _authenticate_config_client(client, access)
                return await client.post(
                    SiteRoute.CONFIG_COLOURS_SAVE.value,
                    data=_csrf_form_values(values, csrf_token),
                    headers=_config_headers(csrf_token),
                )

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "theme_colors.json"
            original_document = DEFAULT_THEME_COLORS_PATH.read_text(encoding="utf-8")
            path.write_text(original_document, encoding="utf-8")
            store = ThemeColorStore(path)
            published_colors = store.load()
            access = _config_access()
            test_app = _isolated_application(theme_colors=store)
            with patch.object(config_security, "CONFIG_ACCESS", access):
                response = asyncio.run(save_palette(test_app, access))
            saved_document = path.read_text(encoding="utf-8")

        self.assertEqual(response.status_code, 422)
        self.assertEqual(saved_document, original_document)
        self.assertEqual(store.published_colors(), published_colors)

    def test_configuration_save_publishes_open_graph_metadata(self) -> None:
        values: dict[str, object] = {
            OpenGraphField.SITE_NAME.value: "APasz Labs",
            OpenGraphField.TITLE.value: "APasz Studio",
            OpenGraphField.DESCRIPTION.value: "A custom sharing description.",
            OpenGraphField.IMAGE_URL.value: "https://example.com/share.png",
        }

        async def save_open_graph(
            test_app: FastHTMLApp,
            access: config_security.ConfigAccess,
        ) -> tuple[httpx.Response, httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=test_app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=CONFIG_TEST_ORIGIN,
            ) as client:
                csrf_token = await _authenticate_config_client(client, access)
                save_response = await client.post(
                    SiteRoute.CONFIG_OPEN_GRAPH_SAVE.value,
                    data=_csrf_form_values(values, csrf_token),
                    headers=_config_headers(csrf_token),
                    follow_redirects=False,
                )
                config_response = await client.get(save_response.headers["location"])
                homepage_response = await client.get(SiteRoute.HOME.value)
                return save_response, config_response, homepage_response

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "open_graph.json"
            path.write_text(
                DEFAULT_OPEN_GRAPH_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            store = OpenGraphStore(path)
            published_metadata = store.load()
            access = _config_access()
            test_app = _isolated_application(open_graph=store)
            with patch.object(config_security, "CONFIG_ACCESS", access):
                save_response, config_response, homepage_response = asyncio.run(
                    save_open_graph(test_app, access)
                )
            saved_metadata = load_open_graph_metadata(path)

        self.assertEqual(save_response.status_code, 303)
        self.assertEqual(
            save_response.headers["location"],
            f"{SiteRoute.CONFIG.value}?open_graph_saved=1",
        )
        self.assertIn("Open Graph saved", config_response.text)
        self.assertIn('value="APasz Studio"', config_response.text)
        self.assertEqual(saved_metadata, store.published_metadata())
        self.assertNotEqual(store.published_metadata(), published_metadata)
        self.assertIn("<title>APasz Studio</title>", homepage_response.text)
        self.assertIn(
            '<meta property="og:title" content="APasz Studio">',
            homepage_response.text,
        )
        self.assertIn(
            '<meta property="og:site_name" content="APasz Labs">',
            homepage_response.text,
        )
        self.assertIn(
            '<meta property="og:description" content="A custom sharing description.">',
            homepage_response.text,
        )
        self.assertIn(
            '<meta property="og:image" content="https://example.com/share.png">',
            homepage_response.text,
        )
        self.assertLess(
            homepage_response.text.index('<meta charset="utf-8">'),
            homepage_response.text.index('<meta property="og:image"'),
        )
        self.assertIn(
            '<meta name="twitter:card" content="summary_large_image">',
            homepage_response.text,
        )


async def _unavailable_repository_count(_: str) -> int:
    raise GithubRepositoryCountUnavailable("GitHub is unavailable in isolated tests.")


def _repository_count_cache() -> GithubRepositoryCountCache:
    return GithubRepositoryCountCache(_unavailable_repository_count)


def _github_fallback_metadata() -> str:
    """Return the configured fallback for the GitHub card under test."""

    for card in load_link_cards():
        if card.schema is not CardKind.GITHUB:
            continue
        if card.metadata is None:
            raise AssertionError(
                "The configured GitHub card must have fallback metadata."
            )
        return card.metadata
    raise AssertionError("The configured link cards must include a GitHub card.")
