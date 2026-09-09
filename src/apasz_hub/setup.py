"""Interactive, safe setup for the private configuration editor."""

from __future__ import annotations

import argparse
import getpass
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
    DEFAULT_PUBLIC_ORIGIN,
    DOTENV_PATH,
    PROJECT_ROOT,
    PUBLIC_ORIGIN_ENV,
)

DOTENV_FILE_MODE: Final[int] = stat.S_IRUSR | stat.S_IWUSR

type PasswordPrompt = Callable[[str], str]


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


class SetupError(RuntimeError):
    """Raised when interactive setup cannot safely create a configuration."""


def main(
    argv: Sequence[str] | None = None,
    *,
    password_prompt: PasswordPrompt = getpass.getpass,
) -> int:
    """Prompt for credentials and atomically create the project dotenv file."""

    arguments = _arguments(argv)
    try:
        if not _target_is_safe_to_write(arguments.replace):
            return 2
        password = _read_password(password_prompt)
        credentials = _new_credentials(password, arguments)
        _write_dotenv(_dotenv_document(credentials), replace=arguments.replace)
    except KeyboardInterrupt:
        print("Setup cancelled.", file=sys.stderr)
        return 1
    except (EOFError, SetupError, OSError) as error:
        print(f"Setup failed: {error}", file=sys.stderr)
        return 1

    print(f"Created {_display_path(DOTENV_PATH)}.")
    print("Configuration access is ready.")
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


def _dotenv_document(credentials: _AccessCredentials) -> str:
    """Serialize only validated dotenv-safe values without displaying them."""

    lines = [
        "# Generated by apasz-hub-setup. Keep this file private.",
        f"{CONFIG_PASSWORD_HASH_ENV}={credentials.password_hash}",
        f"{CONFIG_SESSION_SECRET_ENV}={credentials.session_secret}",
        f"{PUBLIC_ORIGIN_ENV}={credentials.public_origin}",
    ]
    if not credentials.cookie_secure:
        lines.append(f"{CONFIG_COOKIE_SECURE_ENV}=false")
    return "\n".join(lines) + "\n"


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
