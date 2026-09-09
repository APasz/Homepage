"""Tests for the interactive dotenv setup command."""

from __future__ import annotations

import os
import stat
from collections.abc import Generator, Iterator
from contextlib import chdir, contextmanager, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from apasz_hub import config_security, settings, setup
from apasz_hub.settings import (
    CONFIG_COOKIE_SECURE_ENV,
    CONFIG_PASSWORD_HASH_ENV,
    CONFIG_SESSION_SECRET_ENV,
    PUBLIC_ORIGIN_ENV,
)


def _password_prompt(values: tuple[str, ...]) -> setup.PasswordPrompt:
    """Return a deterministic password prompt for an isolated command test."""

    remaining: Iterator[str] = iter(values)

    def prompt(_: str) -> str:
        return next(remaining)

    return prompt


@contextmanager
def _temporary_setup_dotenv(dotenv_path: Path) -> Generator[None]:
    """Point setup and settings at the same isolated dotenv file."""

    with (
        patch.object(setup, "DOTENV_PATH", dotenv_path),
        patch.dict(
            settings.ApplicationSettings.model_config,
            {"env_file": dotenv_path},
        ),
    ):
        yield


class SetupCommandTests(TestCase):
    """Ensure one-command setup is valid, private, and non-destructive by default."""

    def test_creates_a_valid_private_dotenv_without_echoing_the_password(self) -> None:
        password = "correct horse battery staple"
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dotenv_path = root / ".env"
            output = StringIO()
            with (
                _temporary_setup_dotenv(dotenv_path),
                redirect_stdout(output),
            ):
                status = setup.main(
                    (),
                    password_prompt=_password_prompt((password, password)),
                )
                document = dotenv_path.read_text(encoding="utf-8")
                file_mode = stat.S_IMODE(dotenv_path.stat().st_mode)
                with chdir(root), patch.dict(os.environ, {}, clear=True):
                    configured = config_security.load_config_security_settings()

        self.assertEqual(status, 0)
        self.assertIsNotNone(configured)
        assert configured is not None
        self.assertTrue(
            config_security.CONFIG_PASSWORD_HASHER.verify(
                configured.password_hash,
                password,
            )
        )
        self.assertEqual(configured.public_origin, "https://apasz.com")
        self.assertTrue(configured.cookie_secure)
        self.assertEqual(file_mode, 0o600)
        self.assertIn(f"{CONFIG_PASSWORD_HASH_ENV}=", document)
        self.assertIn(f"{CONFIG_SESSION_SECRET_ENV}=", document)
        self.assertIn(f"{PUBLIC_ORIGIN_ENV}=https://apasz.com", document)
        self.assertNotIn(password, document)
        self.assertNotIn(password, output.getvalue())

    def test_existing_dotenv_is_not_overwritten_or_prompted_without_replace(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            dotenv_path = Path(temporary_directory) / ".env"
            original_document = "PORT=6000\n"
            dotenv_path.write_text(original_document, encoding="utf-8")
            errors = StringIO()

            def unexpected_prompt(_: str) -> str:
                raise AssertionError("The password prompt should not be reached.")

            with (
                patch.object(setup, "DOTENV_PATH", dotenv_path),
                redirect_stderr(errors),
            ):
                status = setup.main((), password_prompt=unexpected_prompt)

            preserved_document = dotenv_path.read_text(encoding="utf-8")

        self.assertEqual(status, 2)
        self.assertEqual(preserved_document, original_document)
        self.assertIn("already exists", errors.getvalue())

    def test_replace_explicitly_rotates_existing_access_credentials(self) -> None:
        password = "new password"
        with TemporaryDirectory() as temporary_directory:
            dotenv_path = Path(temporary_directory) / ".env"
            dotenv_path.write_text("PORT=6000\n", encoding="utf-8")
            with (
                patch.object(setup, "DOTENV_PATH", dotenv_path),
                redirect_stdout(StringIO()),
            ):
                status = setup.main(
                    ("--replace", "--origin", "https://example.com"),
                    password_prompt=_password_prompt((password, password)),
                )

            document = dotenv_path.read_text(encoding="utf-8")
            file_mode = stat.S_IMODE(dotenv_path.stat().st_mode)

        self.assertEqual(status, 0)
        self.assertNotIn("PORT=6000", document)
        self.assertIn(f"{PUBLIC_ORIGIN_ENV}=https://example.com", document)
        self.assertNotIn(password, document)
        self.assertEqual(file_mode, 0o600)

    def test_mismatched_passwords_leave_no_dotenv_file(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            dotenv_path = Path(temporary_directory) / ".env"
            errors = StringIO()
            with (
                patch.object(setup, "DOTENV_PATH", dotenv_path),
                redirect_stderr(errors),
            ):
                status = setup.main(
                    (),
                    password_prompt=_password_prompt(("first", "second")),
                )

            self.assertFalse(dotenv_path.exists())

        self.assertEqual(status, 1)
        self.assertIn("do not match", errors.getvalue())

    def test_loopback_http_requires_the_explicit_insecure_cookie_option(self) -> None:
        password = "development password"
        with TemporaryDirectory() as temporary_directory:
            root = Path(temporary_directory)
            dotenv_path = root / ".env"
            with (
                _temporary_setup_dotenv(dotenv_path),
                redirect_stdout(StringIO()),
            ):
                status = setup.main(
                    (
                        "--origin",
                        "http://127.0.0.1:2036",
                        "--insecure-cookie",
                    ),
                    password_prompt=_password_prompt((password, password)),
                )
                document = dotenv_path.read_text(encoding="utf-8")
                with chdir(root), patch.dict(os.environ, {}, clear=True):
                    configured = config_security.load_config_security_settings()

        self.assertEqual(status, 0)
        self.assertIsNotNone(configured)
        assert configured is not None
        self.assertFalse(configured.cookie_secure)
        self.assertIn(f"{CONFIG_COOKIE_SECURE_ENV}=false", document)
