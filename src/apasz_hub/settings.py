"""Typed application settings loaded from the repository dotenv file or environment."""

from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Final

from pydantic import Field, SecretStr, ValidationError, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict, SettingsError

PORT_ENV: Final = "PORT"
HOST_ENV: Final = "HOST"
LINK_CARDS_PATH_ENV: Final = "LINK_CARDS_PATH"
THEME_COLORS_PATH_ENV: Final = "THEME_COLORS_PATH"
OPEN_GRAPH_PATH_ENV: Final = "OPEN_GRAPH_PATH"
CONFIG_PASSWORD_HASH_ENV: Final = "CONFIG_PASSWORD_HASH"
CONFIG_SESSION_SECRET_ENV: Final = "CONFIG_SESSION_SECRET"
PUBLIC_ORIGIN_ENV: Final = "PUBLIC_ORIGIN"
CONFIG_COOKIE_SECURE_ENV: Final = "CONFIG_COOKIE_SECURE"
DEFAULT_PORT: Final = 2036
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PUBLIC_ORIGIN: Final = "https://apasz.com"
PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[2]
DOTENV_PATH: Final[Path] = PROJECT_ROOT / ".env"

_FIELD_ENV_NAMES: Final = {
    "port": PORT_ENV,
    "host": HOST_ENV,
    "link_cards_path": LINK_CARDS_PATH_ENV,
    "theme_colors_path": THEME_COLORS_PATH_ENV,
    "open_graph_path": OPEN_GRAPH_PATH_ENV,
    "config_password_hash": CONFIG_PASSWORD_HASH_ENV,
    "config_session_secret": CONFIG_SESSION_SECRET_ENV,
    "public_origin": PUBLIC_ORIGIN_ENV,
    "config_cookie_secure": CONFIG_COOKIE_SECURE_ENV,
}


class SettingsValidationError(ValueError):
    """Raised when a deployment setting is invalid without exposing secret values."""


class ApplicationSettings(BaseSettings):
    """Validated runtime configuration for the single deployed application."""

    model_config = SettingsConfigDict(
        env_file=DOTENV_PATH,
        env_file_encoding="utf-8",
        extra="forbid",
        frozen=True,
        populate_by_name=True,
    )

    port: int = Field(default=DEFAULT_PORT, validation_alias=PORT_ENV)
    host: str = Field(default=DEFAULT_HOST, validation_alias=HOST_ENV)
    link_cards_path: Path | None = Field(
        default=None,
        validation_alias=LINK_CARDS_PATH_ENV,
    )
    theme_colors_path: Path | None = Field(
        default=None,
        validation_alias=THEME_COLORS_PATH_ENV,
    )
    open_graph_path: Path | None = Field(
        default=None,
        validation_alias=OPEN_GRAPH_PATH_ENV,
    )
    config_password_hash: SecretStr | None = Field(
        default=None,
        validation_alias=CONFIG_PASSWORD_HASH_ENV,
    )
    config_session_secret: SecretStr | None = Field(
        default=None,
        validation_alias=CONFIG_SESSION_SECRET_ENV,
    )
    public_origin: str = Field(
        default=DEFAULT_PUBLIC_ORIGIN,
        validation_alias=PUBLIC_ORIGIN_ENV,
    )
    config_cookie_secure: bool = Field(
        default=True,
        validation_alias=CONFIG_COOKIE_SECURE_ENV,
    )

    @field_validator("port", mode="before")
    @classmethod
    def _validate_port(cls, value: object) -> int:
        """Accept only a conventional valid TCP port."""

        if isinstance(value, bool):
            raise TypeError("PORT must be an integer between 1 and 65535.")
        if isinstance(value, int):
            port = value
        elif isinstance(value, str):
            try:
                port = int(value)
            except ValueError as error:
                raise ValueError(
                    "PORT must be an integer between 1 and 65535."
                ) from error
        else:
            raise TypeError("PORT must be an integer between 1 and 65535.")
        if not 1 <= port <= 65_535:
            raise ValueError("PORT must be an integer between 1 and 65535.")
        return port

    @field_validator("host", "public_origin")
    @classmethod
    def _validate_non_empty_text(cls, value: str) -> str:
        """Reject whitespace-only deployment settings."""

        value = value.strip()
        if not value:
            raise ValueError("must not be empty.")
        return value

    @field_validator(
        "link_cards_path",
        "theme_colors_path",
        "open_graph_path",
        mode="before",
    )
    @classmethod
    def _validate_optional_path(cls, value: object) -> object:
        """Reject an explicitly blank path while accepting an omitted value."""

        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("must not be empty.")
        return value

    @field_validator("config_password_hash", "config_session_secret", mode="before")
    @classmethod
    def _validate_optional_secret(cls, value: object) -> object:
        """Reject an explicitly blank secret rather than treating it as absent."""

        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("must not be empty.")
        return value

    @field_validator("config_cookie_secure", mode="before")
    @classmethod
    def _validate_cookie_secure(cls, value: object) -> bool:
        """Keep the cookie transport override explicit and predictable."""

        if isinstance(value, bool):
            return value
        if value == "true":
            return True
        if value == "false":
            return False
        raise ValueError("CONFIG_COOKIE_SECURE must be 'true' or 'false'.")


def load_settings(
    environment: Mapping[str, str] | None = None,
) -> ApplicationSettings:
    """Load settings from the repository dotenv and process, or a test mapping."""

    try:
        if environment is None:
            return ApplicationSettings()
        return ApplicationSettings.model_validate(
            {
                PORT_ENV: environment.get(PORT_ENV, DEFAULT_PORT),
                HOST_ENV: environment.get(HOST_ENV, DEFAULT_HOST),
                LINK_CARDS_PATH_ENV: environment.get(LINK_CARDS_PATH_ENV),
                THEME_COLORS_PATH_ENV: environment.get(THEME_COLORS_PATH_ENV),
                OPEN_GRAPH_PATH_ENV: environment.get(OPEN_GRAPH_PATH_ENV),
                CONFIG_PASSWORD_HASH_ENV: environment.get(CONFIG_PASSWORD_HASH_ENV),
                CONFIG_SESSION_SECRET_ENV: environment.get(CONFIG_SESSION_SECRET_ENV),
                PUBLIC_ORIGIN_ENV: environment.get(
                    PUBLIC_ORIGIN_ENV,
                    DEFAULT_PUBLIC_ORIGIN,
                ),
                CONFIG_COOKIE_SECURE_ENV: environment.get(
                    CONFIG_COOKIE_SECURE_ENV,
                    True,
                ),
            }
        )
    except ValidationError as error:
        raise SettingsValidationError(_validation_message(error)) from None
    except OSError, SettingsError, UnicodeError:
        raise SettingsValidationError("Unable to load application settings.") from None


def _validation_message(error: ValidationError) -> str:
    """Format validation failures without including the potentially secret input."""

    details = error.errors(include_input=False)
    messages = tuple(
        f"{'.'.join(_display_location_part(part) for part in detail['loc'])}: "
        f"{detail['msg'].removeprefix('Value error, ')}"
        for detail in details
    )
    return "Invalid application settings: " + "; ".join(messages)


def _display_location_part(value: str | int) -> str:
    """Present validation locations using the documented dotenv setting name."""

    if isinstance(value, str):
        return _FIELD_ENV_NAMES.get(value, value)
    return str(value)
