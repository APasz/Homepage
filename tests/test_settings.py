"""Tests for typed deployment settings and dotenv loading."""

from __future__ import annotations

import os
from collections.abc import Generator
from contextlib import chdir, contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from pydantic_settings import SettingsError

from apasz_hub import settings
from apasz_hub.settings import (
    CONFIG_COOKIE_SECURE_ENV,
    CONFIG_PASSWORD_HASH_ENV,
    CONFIG_SESSION_SECRET_ENV,
    DEFAULT_HOST,
    DEFAULT_PORT,
    DEFAULT_PUBLIC_ORIGIN,
    DOTENV_PATH,
    HOST_ENV,
    PORT_ENV,
    PROJECT_ROOT,
    PUBLIC_ORIGIN_ENV,
    ApplicationSettings,
    SettingsValidationError,
    load_settings,
)


@contextmanager
def _temporary_dotenv(document: str) -> Generator[None]:
    """Configure an absolute test dotenv while the process uses another cwd."""

    with TemporaryDirectory() as temporary_directory:
        project_directory = Path(temporary_directory)
        dotenv_path = project_directory / ".env"
        working_directory = project_directory / "service"
        working_directory.mkdir()
        dotenv_path.write_text(document, encoding="utf-8")
        with (
            chdir(working_directory),
            patch.dict(
                ApplicationSettings.model_config,
                {"env_file": dotenv_path},
            ),
        ):
            yield


class ApplicationSettingsTests(TestCase):
    """Keep dotenv configuration concise, typed, and predictable."""

    def test_dotenv_path_is_anchored_at_the_project_root(self) -> None:
        self.assertTrue(DOTENV_PATH.is_absolute())
        self.assertEqual(DOTENV_PATH, PROJECT_ROOT / ".env")
        self.assertEqual(ApplicationSettings.model_config.get("env_file"), DOTENV_PATH)

    def test_dotenv_loads_short_names_without_expanding_an_argon_hash(self) -> None:
        password_hash = "$argon2id$v=19$m=19456,t=2,p=1$salt$hash"
        session_secret = "s" * 43
        dotenv_document = "\n".join(
            (
                f"{CONFIG_PASSWORD_HASH_ENV}={password_hash}",
                f"{CONFIG_SESSION_SECRET_ENV}={session_secret}",
                f"{PUBLIC_ORIGIN_ENV}=https://admin.example",
                f"{CONFIG_COOKIE_SECURE_ENV}=true",
            )
        )
        with (
            _temporary_dotenv(dotenv_document),
            patch.dict(
                os.environ,
                {},
                clear=True,
            ),
        ):
            settings = load_settings()

        configured_hash = settings.config_password_hash
        configured_secret = settings.config_session_secret
        self.assertIsNotNone(configured_hash)
        self.assertIsNotNone(configured_secret)
        assert configured_hash is not None
        assert configured_secret is not None
        self.assertEqual(configured_hash.get_secret_value(), password_hash)
        self.assertEqual(configured_secret.get_secret_value(), session_secret)
        self.assertEqual(settings.public_origin, "https://admin.example")
        self.assertTrue(settings.config_cookie_secure)

    def test_process_environment_overrides_dotenv_values(self) -> None:
        with (
            _temporary_dotenv(f"{PORT_ENV}=6000"),
            patch.dict(
                os.environ,
                {PORT_ENV: "7000"},
                clear=True,
            ),
        ):
            settings = load_settings()

        self.assertEqual(settings.port, 7000)

    def test_defaults_keep_access_closed_until_both_secrets_are_set(self) -> None:
        settings = load_settings({})

        self.assertEqual(settings.port, DEFAULT_PORT)
        self.assertEqual(settings.host, DEFAULT_HOST)
        self.assertEqual(settings.public_origin, DEFAULT_PUBLIC_ORIGIN)
        self.assertIsNone(settings.config_password_hash)
        self.assertIsNone(settings.config_session_secret)

    def test_explicit_test_settings_do_not_read_process_environment(self) -> None:
        with patch.dict(os.environ, {PORT_ENV: "7000", HOST_ENV: "0.0.0.0"}):
            settings = load_settings({PORT_ENV: "5100"})

        self.assertEqual(settings.port, 5100)
        self.assertEqual(settings.host, DEFAULT_HOST)

    def test_invalid_cookie_override_fails_without_echoing_secrets(self) -> None:
        with self.assertRaisesRegex(
            SettingsValidationError,
            f"{CONFIG_COOKIE_SECURE_ENV}: CONFIG_COOKIE_SECURE must be 'true' or 'false'",
        ) as raised:
            load_settings(
                {
                    CONFIG_PASSWORD_HASH_ENV: "sensitive-value",
                    CONFIG_COOKIE_SECURE_ENV: "True",
                }
            )

        self.assertNotIn("sensitive-value", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)

    def test_unknown_dotenv_setting_fails_loudly(self) -> None:
        with (
            _temporary_dotenv("TYPOGRAPHICAL_SETTING=value"),
            patch.dict(os.environ, {}, clear=True),
            self.assertRaises(SettingsValidationError),
        ):
            load_settings()

    def test_settings_source_failures_are_safe_and_consistent(self) -> None:
        with (
            patch.object(
                settings,
                "ApplicationSettings",
                side_effect=SettingsError("contains sensitive configuration"),
            ),
            self.assertRaisesRegex(
                SettingsValidationError,
                "Unable to load application settings",
            ) as raised,
        ):
            load_settings()

        self.assertNotIn("sensitive configuration", str(raised.exception))
        self.assertIsNone(raised.exception.__cause__)
