"""Security regression checks for the private configuration editor."""

from __future__ import annotations

import asyncio
from base64 import urlsafe_b64encode
from collections.abc import Callable
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

import httpx

from apasz_hub import config_security
from apasz_hub.app import app
from apasz_hub.application import create_application
from apasz_hub.framework import FastHTMLApp
from apasz_hub.routes.paths import SiteRoute
from apasz_hub.services import create_application_services
from apasz_hub.theme import (
    DEFAULT_THEME_COLORS_PATH,
    ThemeColorStore,
    load_theme_colors,
)

TEST_ORIGIN = "https://testserver"
TEST_PASSWORD = "correct horse battery staple"
TEST_ENVIRONMENT = {
    config_security.CONFIG_PASSWORD_HASH_ENV: config_security.CONFIG_PASSWORD_HASHER.hash(
        TEST_PASSWORD
    ),
    config_security.CONFIG_SESSION_SECRET_ENV: urlsafe_b64encode(b"s" * 32)
    .decode()
    .rstrip("="),
    config_security.PUBLIC_ORIGIN_ENV: TEST_ORIGIN,
}


def _access(
    *,
    clock: Callable[[], float] | None = None,
) -> config_security.ConfigAccess:
    """Create isolated access state backed by the stable test environment."""

    if clock is None:
        return config_security.ConfigAccess(environment=TEST_ENVIRONMENT)
    return config_security.ConfigAccess(
        environment=TEST_ENVIRONMENT,
        clock=clock,
    )


async def _login(
    client: httpx.AsyncClient,
    access: config_security.ConfigAccess,
) -> str:
    """Authenticate one HTTPS test client and return its CSRF token."""

    response = await client.post(
        SiteRoute.CONFIG_LOGIN.value,
        data={config_security.CONFIG_PASSWORD_FORM_NAME: TEST_PASSWORD},
        headers={"Origin": TEST_ORIGIN},
        follow_redirects=False,
    )
    if response.status_code != 303:
        raise AssertionError(f"Expected login redirect, got {response.status_code}.")
    settings = access.settings()
    if settings is None:
        raise AssertionError("Test authentication unexpectedly became unavailable.")
    session_id = client.cookies.get(
        config_security.configuration_session_cookie_name(settings),
    )
    session = access.authenticate(session_id)
    if session is None:
        raise AssertionError("Successful login did not produce a usable session.")
    return session.csrf_token


def _csrf_form(token: str) -> dict[str, str]:
    """Build a complete valid colour form with its CSRF token."""

    values = {color.token.value: color.value for color in load_theme_colors()}
    values[config_security.CONFIG_CSRF_FORM_NAME] = token
    return values


def _csrf_headers(token: str, *, origin: str = TEST_ORIGIN) -> dict[str, str]:
    """Return browser request metadata for an authenticated config form."""

    return {
        "Origin": origin,
        config_security.CONFIG_CSRF_HEADER: token,
    }


class ConfigSecurityTests(TestCase):
    """Ensure every configuration mutation is behind the intended defences."""

    def test_unconfigured_access_fails_closed(self) -> None:
        async def request_config() -> tuple[httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=TEST_ORIGIN,
                follow_redirects=False,
            ) as client:
                return (
                    await client.get(SiteRoute.CONFIG.value),
                    await client.get(SiteRoute.CONFIG_LOGIN.value),
                )

        with patch.object(
            config_security,
            "CONFIG_ACCESS",
            config_security.ConfigAccess(environment={}),
        ):
            config_response, login_response = asyncio.run(request_config())

        for response in (config_response, login_response):
            self.assertEqual(response.status_code, 503)
            self.assertEqual(response.headers["cache-control"], "no-store")
            self.assertIn(
                "frame-ancestors 'none'", response.headers["content-security-policy"]
            )

    def test_insecure_configuration_cookies_are_limited_to_loopback_development(
        self,
    ) -> None:
        loopback_environment = {
            **TEST_ENVIRONMENT,
            config_security.PUBLIC_ORIGIN_ENV: "http://127.0.0.1:2036",
            config_security.CONFIG_COOKIE_SECURE_ENV: "false",
        }
        settings = config_security.load_config_security_settings(loopback_environment)

        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertFalse(settings.cookie_secure)

        public_http_environment = {
            **loopback_environment,
            config_security.PUBLIC_ORIGIN_ENV: "http://example.com",
        }
        with self.assertRaisesRegex(
            config_security.ConfigSecurityConfigurationError,
            "must use HTTPS",
        ):
            config_security.load_config_security_settings(public_http_environment)

    def test_canonical_origin_is_used_when_access_secrets_are_configured(self) -> None:
        settings = config_security.load_config_security_settings(
            {
                name: value
                for name, value in TEST_ENVIRONMENT.items()
                if name != config_security.PUBLIC_ORIGIN_ENV
            }
        )

        self.assertIsNotNone(settings)
        assert settings is not None
        self.assertEqual(settings.public_origin, "https://apasz.com")

    def test_access_settings_reject_invalid_origins_and_non_urlsafe_secrets(
        self,
    ) -> None:
        for origin in (
            "https://example.com%20",
            "https://-example.com",
            "https://example..com",
            "https://example.com:",
        ):
            with (
                self.subTest(origin=origin),
                self.assertRaisesRegex(
                    config_security.ConfigSecurityConfigurationError,
                    "public origin",
                ),
            ):
                config_security.load_config_security_settings(
                    {
                        **TEST_ENVIRONMENT,
                        config_security.PUBLIC_ORIGIN_ENV: origin,
                    }
                )

        for session_secret in ("+" * 43, "/" * 43):
            with (
                self.subTest(session_secret=session_secret),
                self.assertRaisesRegex(
                    config_security.ConfigSecurityConfigurationError,
                    "URL-safe base64",
                ),
            ):
                config_security.load_config_security_settings(
                    {
                        **TEST_ENVIRONMENT,
                        config_security.CONFIG_SESSION_SECRET_ENV: session_secret,
                    }
                )

    def test_access_settings_accept_padded_urlsafe_secrets_and_redact_them(
        self,
    ) -> None:
        session_secret = urlsafe_b64encode(b"p" * 32).decode()
        configured = config_security.load_config_security_settings(
            {
                **TEST_ENVIRONMENT,
                config_security.CONFIG_SESSION_SECRET_ENV: session_secret,
            }
        )

        self.assertIsNotNone(configured)
        assert configured is not None
        self.assertEqual(configured.session_secret, b"p" * 32)
        rendered = repr(configured)
        self.assertNotIn(configured.password_hash, rendered)
        self.assertNotIn(repr(configured.session_secret), rendered)

        access = _access()
        outcome = access.login("127.0.0.1", TEST_PASSWORD)
        self.assertIsNotNone(outcome.session_id)
        assert outcome.session_id is not None
        self.assertNotIn(outcome.session_id, repr(outcome))
        session = access.authenticate(outcome.session_id)
        self.assertIsNotNone(session)
        assert session is not None
        self.assertNotIn(session.csrf_token, repr(session))

    def test_unauthenticated_requests_cannot_reach_any_config_write_route(self) -> None:
        async def make_requests() -> tuple[httpx.Response, tuple[httpx.Response, ...]]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=TEST_ORIGIN,
                follow_redirects=False,
            ) as client:
                page = await client.get(SiteRoute.CONFIG.value)
                writes: list[httpx.Response] = []
                for path in (
                    SiteRoute.CONFIG_COLOURS_SAVE.value,
                    SiteRoute.CONFIG_LINK_CARDS_DRAFT.value,
                    SiteRoute.CONFIG_LINK_CARDS_ADD.value,
                    SiteRoute.CONFIG_LINK_CARDS_DELETE.value,
                    SiteRoute.CONFIG_LINK_CARDS_SAVE.value,
                ):
                    writes.append(
                        await client.post(path, headers={"Origin": TEST_ORIGIN})
                    )
                return page, tuple(writes)

        access = _access()
        with patch.object(config_security, "CONFIG_ACCESS", access):
            page, writes = asyncio.run(make_requests())

        self.assertEqual(page.status_code, 303)
        self.assertEqual(page.headers["location"], SiteRoute.CONFIG_LOGIN.value)
        for response in writes:
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.headers["cache-control"], "no-store")

    def test_login_requires_same_origin_and_issues_a_secure_cookie(self) -> None:
        async def login_requests() -> tuple[
            httpx.Response, httpx.Response, httpx.Response
        ]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=TEST_ORIGIN,
                follow_redirects=False,
            ) as client:
                missing_origin = await client.post(
                    SiteRoute.CONFIG_LOGIN.value,
                    data={config_security.CONFIG_PASSWORD_FORM_NAME: TEST_PASSWORD},
                )
                invalid_password = await client.post(
                    SiteRoute.CONFIG_LOGIN.value,
                    data={config_security.CONFIG_PASSWORD_FORM_NAME: "incorrect"},
                    headers={"Origin": TEST_ORIGIN},
                )
                valid_login = await client.post(
                    SiteRoute.CONFIG_LOGIN.value,
                    data={config_security.CONFIG_PASSWORD_FORM_NAME: TEST_PASSWORD},
                    headers={"Origin": TEST_ORIGIN},
                )
                return missing_origin, invalid_password, valid_login

        access = _access()
        with (
            patch.object(config_security, "CONFIG_ACCESS", access),
            self.assertLogs("apasz_hub.routes.authentication", level="WARNING") as logs,
        ):
            missing_origin, invalid_password, valid_login = asyncio.run(
                login_requests()
            )

        self.assertEqual(len(logs.output), 1)
        self.assertIn("Configuration login failed", logs.output[0])
        self.assertEqual(missing_origin.status_code, 403)
        self.assertEqual(invalid_password.status_code, 303)
        self.assertEqual(
            invalid_password.headers["location"],
            f"{SiteRoute.CONFIG_LOGIN.value}?failed=1",
        )
        self.assertEqual(valid_login.status_code, 303)
        self.assertEqual(valid_login.headers["location"], SiteRoute.CONFIG.value)
        cookie = valid_login.headers["set-cookie"]
        self.assertIn("__Host-apasz-config-session=", cookie)
        self.assertIn("HttpOnly", cookie)
        self.assertIn("Max-Age=28800", cookie)
        self.assertIn("Path=/", cookie)
        self.assertIn("SameSite=strict", cookie)
        self.assertIn("Secure", cookie)

    def test_authenticated_writes_require_matching_origin_and_csrf_token(self) -> None:
        async def make_requests(
            test_app: FastHTMLApp,
        ) -> tuple[
            httpx.Response,
            httpx.Response,
            httpx.Response,
            httpx.Response,
        ]:
            transport = httpx.ASGITransport(app=test_app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=TEST_ORIGIN,
                follow_redirects=False,
            ) as client:
                token = await _login(client, access)
                missing_token = await client.post(
                    SiteRoute.CONFIG_COLOURS_SAVE.value,
                    data={
                        color.token.value: color.value for color in load_theme_colors()
                    },
                    headers={"Origin": TEST_ORIGIN},
                )
                invalid_token = await client.post(
                    SiteRoute.CONFIG_COLOURS_SAVE.value,
                    data=_csrf_form("invalid"),
                    headers=_csrf_headers("invalid"),
                )
                wrong_origin = await client.post(
                    SiteRoute.CONFIG_COLOURS_SAVE.value,
                    data=_csrf_form(token),
                    headers=_csrf_headers(token, origin="https://attacker.example"),
                )
                valid = await client.post(
                    SiteRoute.CONFIG_COLOURS_SAVE.value,
                    data=_csrf_form(token),
                    headers=_csrf_headers(token),
                )
                return missing_token, invalid_token, wrong_origin, valid

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "theme_colors.json"
            path.write_text(
                DEFAULT_THEME_COLORS_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            access = _access()
            theme_color_store = ThemeColorStore(path)
            test_app = create_application(
                create_application_services(theme_colors=theme_color_store),
            )
            with (
                patch.object(config_security, "CONFIG_ACCESS", access),
            ):
                missing_token, invalid_token, wrong_origin, valid = asyncio.run(
                    make_requests(test_app)
                )

        self.assertEqual(missing_token.status_code, 403)
        self.assertEqual(invalid_token.status_code, 403)
        self.assertEqual(wrong_origin.status_code, 403)
        self.assertEqual(valid.status_code, 303)

    def test_logout_invalidates_the_server_side_session(self) -> None:
        async def logout_then_request() -> tuple[httpx.Response, httpx.Response]:
            transport = httpx.ASGITransport(app=app)
            async with httpx.AsyncClient(
                transport=transport,
                base_url=TEST_ORIGIN,
                follow_redirects=False,
            ) as client:
                token = await _login(client, access)
                logout = await client.post(
                    SiteRoute.CONFIG_LOGOUT.value,
                    data={config_security.CONFIG_CSRF_FORM_NAME: token},
                    headers=_csrf_headers(token),
                )
                page = await client.get(SiteRoute.CONFIG.value)
                return logout, page

        access = _access()
        with patch.object(config_security, "CONFIG_ACCESS", access):
            logout, page = asyncio.run(logout_then_request())

        self.assertEqual(logout.status_code, 303)
        self.assertEqual(logout.headers["location"], SiteRoute.CONFIG_LOGIN.value)
        self.assertIn("Max-Age=0", logout.headers["set-cookie"])
        self.assertEqual(page.status_code, 303)
        self.assertEqual(page.headers["location"], SiteRoute.CONFIG_LOGIN.value)

    def test_server_side_sessions_expire_after_the_idle_limit(self) -> None:
        now = 0.0

        def clock() -> float:
            return now

        access = _access(clock=clock)
        outcome = access.login("127.0.0.1", TEST_PASSWORD)
        self.assertIs(outcome.result, config_security.LoginResult.AUTHENTICATED)
        self.assertIsNotNone(outcome.session_id)
        assert outcome.session_id is not None
        self.assertIsNotNone(access.authenticate(outcome.session_id))
        now = config_security.CONFIG_SESSION_IDLE_SECONDS + 1
        self.assertIsNone(access.authenticate(outcome.session_id))

    def test_login_is_rate_limited_after_repeated_failures(self) -> None:
        access = _access()
        for _ in range(config_security.LOGIN_FAILURE_LIMIT):
            outcome = access.login("127.0.0.1", "incorrect")
            self.assertIs(outcome.result, config_security.LoginResult.INVALID)

        outcome = access.login("127.0.0.1", TEST_PASSWORD)

        self.assertIs(outcome.result, config_security.LoginResult.RATE_LIMITED)
        self.assertIsNotNone(outcome.retry_after_seconds)
