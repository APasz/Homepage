"""Interactive setup for private configuration access and optional SMTP email."""

from __future__ import annotations

import argparse
import getpass
import json
import os
import secrets
import stat
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final, cast

from argon2.exceptions import Argon2Error

from apasz_hub import config_security
from apasz_hub.settings import (
    CONFIG_COOKIE_SECURE_ENV,
    CONFIG_PASSWORD_HASH_ENV,
    CONFIG_SESSION_SECRET_ENV,
    DEFAULT_EMAIL_SMTP_PORT,
    DEFAULT_PUBLIC_ORIGIN,
    DOTENV_PATH,
    EMAIL_FROM_ENV,
    EMAIL_NOTIFICATION_EVENTS_ENV,
    EMAIL_SMTP_HOST_ENV,
    EMAIL_SMTP_PASSWORD_ENV,
    EMAIL_SMTP_PORT_ENV,
    EMAIL_SMTP_SECURITY_ENV,
    EMAIL_SMTP_USERNAME_ENV,
    EMAIL_TO_ENV,
    PROJECT_ROOT,
    PUBLIC_ORIGIN_ENV,
    EmailNotificationEvent,
    EmailSmtpSecurity,
    SettingsValidationError,
    load_settings,
)

DOTENV_FILE_MODE: Final[int] = stat.S_IRUSR | stat.S_IWUSR

type PasswordPrompt = Callable[[str], str]
type TextPrompt = Callable[[str], str]

DEFAULT_EMAIL_NOTIFICATION_EVENTS: Final = ",".join(
    event.value for event in EmailNotificationEvent
)


@dataclass(frozen=True, slots=True)
class SetupArguments:
    """Explicit options for configuring the local administrator access."""

    origin: str
    insecure_cookie: bool
    replace: bool


@dataclass(frozen=True, slots=True)
class _AccessCredentials:
    """Fresh secret material prepared for a new dotenv file."""

    password_hash: str = field(repr=False)
    session_secret: str = field(repr=False)
    public_origin: str
    cookie_secure: bool


@dataclass(frozen=True, slots=True)
class _EmailConfiguration:
    """Validated SMTP notification values selected during interactive setup."""

    events: frozenset[EmailNotificationEvent]
    smtp_host: str
    smtp_port: int
    smtp_security: EmailSmtpSecurity
    sender: str
    recipients: tuple[str, ...]
    smtp_username: str | None = None
    smtp_password: str | None = field(default=None, repr=False)


class SetupError(RuntimeError):
    """Raised when interactive setup cannot safely create a configuration."""


def main(
    argv: Sequence[str] | None = None,
    *,
    password_prompt: PasswordPrompt = getpass.getpass,
    text_prompt: TextPrompt = input,
) -> int:
    """Prompt for access and optional SMTP settings, then atomically create .env."""

    arguments = _arguments(argv)
    try:
        if not _target_is_safe_to_write(arguments.replace):
            return 2
        password = _read_password(password_prompt)
        credentials = _new_credentials(password, arguments)
        email_configuration = _read_optional_email_configuration(
            text_prompt,
            password_prompt,
        )
        _write_dotenv(
            _dotenv_document(credentials, email_configuration),
            replace=arguments.replace,
        )
    except KeyboardInterrupt:
        print("Setup cancelled.", file=sys.stderr)
        return 1
    except (EOFError, SetupError, OSError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        return 1

    print(f"Created {_display_path(DOTENV_PATH)}.")
    if email_configuration is None:
        print("Configuration access is ready.")
    else:
        print("Configuration access and email notifications are ready.")
        print("Run `uv run apasz-hub-email-test` to verify SMTP delivery.")
    return 0


def _arguments(argv: Sequence[str] | None) -> SetupArguments:
    """Parse the small explicit set of setup options."""

    parser = argparse.ArgumentParser(
        description="Create a protected .env for the APasz configuration editor.",
    )
    parser.add_argument(
        "--origin",
        default=DEFAULT_PUBLIC_ORIGIN,
        help=f"external browser origin (default: {DEFAULT_PUBLIC_ORIGIN})",
    )
    parser.add_argument(
        "--insecure-cookie",
        action="store_true",
        help="allow an HTTP loopback origin for local development only",
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="replace an existing .env after generating fresh credentials",
    )
    parsed = parser.parse_args(argv)
    return SetupArguments(
        origin=cast(str, parsed.origin),
        insecure_cookie=cast(bool, parsed.insecure_cookie),
        replace=cast(bool, parsed.replace),
    )


def _target_is_safe_to_write(replace: bool) -> bool:
    """Refuse accidental replacement or a path that could redirect secret writes."""

    if DOTENV_PATH.is_symlink():
        print(
            f"Refusing to write through symbolic link: {DOTENV_PATH}", file=sys.stderr
        )
        return False
    if not DOTENV_PATH.exists():
        return True
    if not DOTENV_PATH.is_file():
        print(f"Refusing to replace non-file path: {DOTENV_PATH}", file=sys.stderr)
        return False
    if replace:
        return True
    print(
        f"{DOTENV_PATH} already exists; use --replace to create fresh credentials.",
        file=sys.stderr,
    )
    return False


def _read_password(password_prompt: PasswordPrompt) -> str:
    """Read a bounded matching password without echoing it to the terminal."""

    password = password_prompt("Configuration password: ")
    if not password:
        raise SetupError("Configuration password must not be empty.")
    if len(password) > config_security.MAX_LOGIN_PASSWORD_LENGTH:
        raise SetupError("Configuration password exceeds the supported maximum length.")
    confirmation = password_prompt("Confirm configuration password: ")
    if password != confirmation:
        raise SetupError("Configuration passwords do not match.")
    return password


def _new_credentials(
    password: str,
    arguments: SetupArguments,
) -> _AccessCredentials:
    """Generate and fully validate fresh access secrets before any file is written."""

    try:
        password_hash = config_security.CONFIG_PASSWORD_HASHER.hash(password)
    except Argon2Error as error:
        raise SetupError("Unable to derive the configuration password hash.") from error
    session_secret = secrets.token_urlsafe(config_security.CONFIG_SESSION_TOKEN_BYTES)
    values = {
        CONFIG_PASSWORD_HASH_ENV: password_hash,
        CONFIG_SESSION_SECRET_ENV: session_secret,
        PUBLIC_ORIGIN_ENV: arguments.origin,
    }
    if arguments.insecure_cookie:
        values[CONFIG_COOKIE_SECURE_ENV] = "false"
    try:
        configured = config_security.load_config_security_settings(values)
    except config_security.ConfigSecurityConfigurationError as error:
        raise SetupError(str(error)) from error
    if configured is None:
        raise SetupError("Generated configuration access settings are incomplete.")
    return _AccessCredentials(
        password_hash=password_hash,
        session_secret=session_secret,
        public_origin=configured.public_origin,
        cookie_secure=configured.cookie_secure,
    )


def _read_optional_email_configuration(
    text_prompt: TextPrompt,
    password_prompt: PasswordPrompt,
) -> _EmailConfiguration | None:
    """Prompt for SMTP notifications only when the operator opts in."""

    if not _confirm(text_prompt, "Configure email notifications? [y/N]: "):
        return None

    events = text_prompt(
        f"Notification events [{DEFAULT_EMAIL_NOTIFICATION_EVENTS}]: "
    ).strip()
    smtp_host = text_prompt("SMTP host: ").strip()
    smtp_port = text_prompt(f"SMTP port [{DEFAULT_EMAIL_SMTP_PORT}]: ").strip()
    smtp_security = text_prompt(
        f"SMTP security [{EmailSmtpSecurity.STARTTLS.value}]: "
    ).strip()
    smtp_username = text_prompt("SMTP username (leave blank for none): ").strip()
    smtp_password: str | None = None
    if smtp_username:
        smtp_password = password_prompt("SMTP password: ")
        if not smtp_password:
            raise SetupError("SMTP password must not be empty when a username is set.")
    sender = text_prompt("Email sender: ").strip()
    recipients = text_prompt("Email recipients (comma-separated): ").strip()

    values = {
        EMAIL_NOTIFICATION_EVENTS_ENV: events or DEFAULT_EMAIL_NOTIFICATION_EVENTS,
        EMAIL_SMTP_HOST_ENV: smtp_host,
        EMAIL_SMTP_PORT_ENV: smtp_port or str(DEFAULT_EMAIL_SMTP_PORT),
        EMAIL_SMTP_SECURITY_ENV: smtp_security or EmailSmtpSecurity.STARTTLS.value,
        EMAIL_FROM_ENV: sender,
        EMAIL_TO_ENV: recipients,
    }
    if smtp_username:
        values[EMAIL_SMTP_USERNAME_ENV] = smtp_username
    if smtp_password is not None:
        values[EMAIL_SMTP_PASSWORD_ENV] = smtp_password
    try:
        configured = load_settings(values)
    except SettingsValidationError as error:
        raise SetupError(str(error)) from error

    configured_smtp_host = configured.email_smtp_host
    configured_sender = configured.email_from
    configured_recipients = configured.email_to
    if (
        configured_smtp_host is None
        or configured_sender is None
        or not configured_recipients
    ):
        raise SetupError("Validated email notification settings are incomplete.")
    configured_password_secret = configured.email_smtp_password
    configured_password = (
        None
        if configured_password_secret is None
        else configured_password_secret.get_secret_value()
    )
    return _EmailConfiguration(
        events=configured.email_notification_events,
        smtp_host=configured_smtp_host,
        smtp_port=configured.email_smtp_port,
        smtp_security=configured.email_smtp_security,
        sender=configured_sender,
        recipients=configured_recipients,
        smtp_username=configured.email_smtp_username,
        smtp_password=configured_password,
    )


def _confirm(text_prompt: TextPrompt, prompt: str) -> bool:
    """Read an explicit yes/no answer, defaulting safely to no."""

    answer = text_prompt(prompt).strip().casefold()
    if answer in {"", "n", "no"}:
        return False
    if answer in {"y", "yes"}:
        return True
    raise SetupError("Please answer yes or no.")


def _dotenv_document(
    credentials: _AccessCredentials,
    email_configuration: _EmailConfiguration | None,
) -> str:
    """Serialize only validated dotenv-safe values without displaying them."""

    lines = [
        "# Generated by apasz-hub-setup. Keep this file private.",
        f"{CONFIG_PASSWORD_HASH_ENV}={credentials.password_hash}",
        f"{CONFIG_SESSION_SECRET_ENV}={credentials.session_secret}",
        f"{PUBLIC_ORIGIN_ENV}={credentials.public_origin}",
    ]
    if not credentials.cookie_secure:
        lines.append(f"{CONFIG_COOKIE_SECURE_ENV}=false")
    if email_configuration is not None:
        lines.extend(_email_dotenv_lines(email_configuration))
    return "\n".join(lines) + "\n"


def _email_dotenv_lines(configuration: _EmailConfiguration) -> list[str]:
    """Serialize SMTP values with dotenv quoting that preserves secrets exactly."""

    event_values = ",".join(
        event.value for event in EmailNotificationEvent if event in configuration.events
    )
    lines = [
        _dotenv_assignment(EMAIL_NOTIFICATION_EVENTS_ENV, event_values),
        _dotenv_assignment(EMAIL_SMTP_HOST_ENV, configuration.smtp_host),
        _dotenv_assignment(EMAIL_SMTP_PORT_ENV, str(configuration.smtp_port)),
        _dotenv_assignment(EMAIL_SMTP_SECURITY_ENV, configuration.smtp_security.value),
        _dotenv_assignment(EMAIL_FROM_ENV, configuration.sender),
        _dotenv_assignment(EMAIL_TO_ENV, ",".join(configuration.recipients)),
    ]
    if configuration.smtp_username is not None:
        password = configuration.smtp_password
        if password is None:
            raise SetupError("SMTP credentials are incomplete.")
        lines.extend(
            (
                _dotenv_assignment(
                    EMAIL_SMTP_USERNAME_ENV, configuration.smtp_username
                ),
                _dotenv_assignment(EMAIL_SMTP_PASSWORD_ENV, password),
            )
        )
    return lines


def _dotenv_assignment(name: str, value: str) -> str:
    """Return one safely quoted UTF-8 dotenv assignment for an SMTP setting."""

    return f"{name}={json.dumps(value, ensure_ascii=False)}"


def _write_dotenv(document: str, *, replace: bool) -> None:
    """Install a mode-600 dotenv atomically without overwriting by default."""

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=DOTENV_PATH.parent,
            prefix=".env-",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            os.fchmod(temporary_file.fileno(), DOTENV_FILE_MODE)
            temporary_file.write(document)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())

        if replace:
            os.replace(temporary_path, DOTENV_PATH)
        else:
            _install_new_dotenv(temporary_path)
        temporary_path = None
    finally:
        if temporary_path is not None:
            temporary_path.unlink(missing_ok=True)


def _install_new_dotenv(temporary_path: Path) -> None:
    """Atomically install a new dotenv without a check-then-replace race."""

    try:
        os.link(temporary_path, DOTENV_PATH)
    except FileExistsError as error:
        raise SetupError(
            f"{DOTENV_PATH} appeared during setup; no credentials were written."
        ) from error
    temporary_path.unlink()


def _display_path(path: Path) -> Path:
    """Prefer a project-relative completion message when the file is in the project."""

    return path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path


if __name__ == "__main__":
    raise SystemExit(main())
