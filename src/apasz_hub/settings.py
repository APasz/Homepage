"""Typed application settings loaded from the repository dotenv file or environment."""

from __future__ import annotations

from collections.abc import Mapping
from email.errors import HeaderParseError
from email.headerregistry import Address
from enum import StrEnum
from pathlib import Path
from typing import Annotated, Final, Self, cast

from pydantic import (
    Field,
    SecretStr,
    ValidationError,
    field_validator,
    model_validator,
)
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict, SettingsError

PORT_ENV: Final = "PORT"
HOST_ENV: Final = "HOST"
LINK_CARDS_PATH_ENV: Final = "LINK_CARDS_PATH"
THEME_COLORS_PATH_ENV: Final = "THEME_COLORS_PATH"
OPEN_GRAPH_PATH_ENV: Final = "OPEN_GRAPH_PATH"
CONFIG_PASSWORD_HASH_ENV: Final = "CONFIG_PASSWORD_HASH"
CONFIG_SESSION_SECRET_ENV: Final = "CONFIG_SESSION_SECRET"
PUBLIC_ORIGIN_ENV: Final = "PUBLIC_ORIGIN"
CONFIG_COOKIE_SECURE_ENV: Final = "CONFIG_COOKIE_SECURE"
EMAIL_NOTIFICATION_EVENTS_ENV: Final = "EMAIL_NOTIFICATION_EVENTS"
EMAIL_SMTP_HOST_ENV: Final = "EMAIL_SMTP_HOST"
EMAIL_SMTP_PORT_ENV: Final = "EMAIL_SMTP_PORT"
EMAIL_SMTP_SECURITY_ENV: Final = "EMAIL_SMTP_SECURITY"
EMAIL_SMTP_USERNAME_ENV: Final = "EMAIL_SMTP_USERNAME"
EMAIL_SMTP_PASSWORD_ENV: Final = "EMAIL_SMTP_PASSWORD"
EMAIL_FROM_ENV: Final = "EMAIL_FROM"
EMAIL_TO_ENV: Final = "EMAIL_TO"
DEFAULT_PORT: Final = 2036
DEFAULT_HOST: Final = "127.0.0.1"
DEFAULT_PUBLIC_ORIGIN: Final = "https://apasz.com"
DEFAULT_EMAIL_SMTP_PORT: Final = 587
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
    "email_notification_events": EMAIL_NOTIFICATION_EVENTS_ENV,
    "email_smtp_host": EMAIL_SMTP_HOST_ENV,
    "email_smtp_port": EMAIL_SMTP_PORT_ENV,
    "email_smtp_security": EMAIL_SMTP_SECURITY_ENV,
    "email_smtp_username": EMAIL_SMTP_USERNAME_ENV,
    "email_smtp_password": EMAIL_SMTP_PASSWORD_ENV,
    "email_from": EMAIL_FROM_ENV,
    "email_to": EMAIL_TO_ENV,
}


class SettingsValidationError(ValueError):
    """Raised when a deployment setting is invalid without exposing secret values."""


class EmailNotificationEvent(StrEnum):
    """Application events that can be delivered to an SMTP mailbox."""

    STARTUP = "startup"
    CONFIGURATION_SAVED = "configuration_saved"


class EmailSmtpSecurity(StrEnum):
    """Transport security modes supported by the SMTP notifier."""

    STARTTLS = "starttls"
    SSL = "ssl"
    NONE = "none"


_EMAIL_SMTP_SECURITY_ALIASES: Final[Mapping[str, EmailSmtpSecurity]] = {
    EmailSmtpSecurity.STARTTLS.value: EmailSmtpSecurity.STARTTLS,
    EmailSmtpSecurity.SSL.value: EmailSmtpSecurity.SSL,
    "ssl/tls": EmailSmtpSecurity.SSL,
    EmailSmtpSecurity.NONE.value: EmailSmtpSecurity.NONE,
}


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
    email_notification_events: Annotated[
        frozenset[EmailNotificationEvent], NoDecode
    ] = Field(
        default_factory=frozenset,
        validation_alias=EMAIL_NOTIFICATION_EVENTS_ENV,
    )
    email_smtp_host: str | None = Field(
        default=None,
        validation_alias=EMAIL_SMTP_HOST_ENV,
    )
    email_smtp_port: int = Field(
        default=DEFAULT_EMAIL_SMTP_PORT,
        validation_alias=EMAIL_SMTP_PORT_ENV,
    )
    email_smtp_security: EmailSmtpSecurity = Field(
        default=EmailSmtpSecurity.STARTTLS,
        validation_alias=EMAIL_SMTP_SECURITY_ENV,
    )
    email_smtp_username: str | None = Field(
        default=None,
        validation_alias=EMAIL_SMTP_USERNAME_ENV,
    )
    email_smtp_password: SecretStr | None = Field(
        default=None,
        validation_alias=EMAIL_SMTP_PASSWORD_ENV,
    )
    email_from: str | None = Field(default=None, validation_alias=EMAIL_FROM_ENV)
    email_to: Annotated[tuple[str, ...], NoDecode] = Field(
        default=(),
        validation_alias=EMAIL_TO_ENV,
    )

    @field_validator("port", mode="before")
    @classmethod
    def _validate_port(cls, value: object) -> int:
        """Accept only a conventional valid TCP port."""

        return _tcp_port(value, PORT_ENV)

    @field_validator("email_smtp_port", mode="before")
    @classmethod
    def _validate_email_smtp_port(cls, value: object) -> int:
        """Accept only a conventional valid SMTP port."""

        return _tcp_port(value, EMAIL_SMTP_PORT_ENV)

    @field_validator("email_smtp_security", mode="before")
    @classmethod
    def _validate_email_smtp_security(cls, value: object) -> EmailSmtpSecurity:
        """Accept canonical SMTP security modes and the common SSL/TLS label."""

        if isinstance(value, EmailSmtpSecurity):
            return value
        if not isinstance(value, str):
            raise TypeError(f"{EMAIL_SMTP_SECURITY_ENV} must be an SMTP security mode.")
        normalised = value.strip().casefold()
        try:
            return _EMAIL_SMTP_SECURITY_ALIASES[normalised]
        except KeyError as error:
            supported = ", ".join(security.value for security in EmailSmtpSecurity)
            raise ValueError(
                f"{EMAIL_SMTP_SECURITY_ENV} must be one of: {supported}."
            ) from error

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

    @field_validator(
        "config_password_hash",
        "config_session_secret",
        "email_smtp_password",
        mode="before",
    )
    @classmethod
    def _validate_optional_secret(cls, value: object) -> object:
        """Reject an explicitly blank secret rather than treating it as absent."""

        if isinstance(value, str) and not value.strip():
            raise ValueError("must not be empty.")
        return value

    @field_validator("email_smtp_host", "email_smtp_username", mode="before")
    @classmethod
    def _validate_optional_email_text(cls, value: object) -> object:
        """Reject blank SMTP connection fields."""

        if isinstance(value, str):
            value = value.strip()
            if not value:
                raise ValueError("must not be empty.")
        return value

    @field_validator("email_smtp_username", "email_smtp_password", mode="before")
    @classmethod
    def _validate_ascii_smtp_credentials(cls, value: object) -> object:
        """Reject credentials the standard-library SMTP AUTH client cannot encode."""

        if isinstance(value, str) and not value.isascii():
            raise ValueError(
                "SMTP authentication values must contain only ASCII characters."
            )
        return value

    @field_validator("email_from", mode="before")
    @classmethod
    def _validate_email_sender(cls, value: object) -> object:
        """Accept an omitted sender or one mailbox address without display text."""

        if value is None:
            return value
        if not isinstance(value, str):
            raise TypeError("EMAIL_FROM must be a mailbox address.")
        sender = value.strip()
        if not _is_mailbox_address(sender):
            raise ValueError("EMAIL_FROM must be a mailbox address.")
        return sender

    @field_validator("email_notification_events", mode="before")
    @classmethod
    def _validate_email_notification_events(cls, value: object) -> object:
        """Parse an explicit comma-separated set of notification event names."""

        if value is None:
            return frozenset[EmailNotificationEvent]()
        if isinstance(value, frozenset):
            event_values = cast(frozenset[object], value)
            if not all(
                isinstance(event, EmailNotificationEvent) for event in event_values
            ):
                raise TypeError(
                    f"{EMAIL_NOTIFICATION_EVENTS_ENV} must contain notification events."
                )
            events = frozenset(
                cast(EmailNotificationEvent, event) for event in event_values
            )
        else:
            values = _comma_separated_values(value, EMAIL_NOTIFICATION_EVENTS_ENV)
            try:
                events = frozenset(EmailNotificationEvent(item) for item in values)
            except ValueError as error:
                supported = ", ".join(event.value for event in EmailNotificationEvent)
                raise ValueError(
                    f"{EMAIL_NOTIFICATION_EVENTS_ENV} must contain only: {supported}."
                ) from error
            if len(events) != len(values):
                raise ValueError(
                    f"{EMAIL_NOTIFICATION_EVENTS_ENV} must not contain duplicate events."
                )
        return events

    @field_validator("email_to", mode="before")
    @classmethod
    def _validate_email_recipients(cls, value: object) -> object:
        """Parse one or more comma-separated mailbox recipients."""

        if value is None:
            return ()
        if isinstance(value, tuple):
            recipient_values = cast(tuple[object, ...], value)
            if not all(isinstance(recipient, str) for recipient in recipient_values):
                raise TypeError(f"{EMAIL_TO_ENV} must contain mailbox addresses only.")
            recipients = tuple(cast(str, recipient) for recipient in recipient_values)
        else:
            recipients = _comma_separated_values(value, EMAIL_TO_ENV)
        if any(not _is_mailbox_address(recipient) for recipient in recipients):
            raise ValueError(f"{EMAIL_TO_ENV} must contain mailbox addresses only.")
        if len(set(recipients)) != len(recipients):
            raise ValueError(f"{EMAIL_TO_ENV} must not contain duplicate addresses.")
        return recipients

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

    @model_validator(mode="after")
    def _validate_email_notification_configuration(self) -> Self:
        """Require enough SMTP configuration whenever email events are enabled."""

        if (self.email_smtp_username is None) != (self.email_smtp_password is None):
            raise ValueError(
                "EMAIL_SMTP_USERNAME and EMAIL_SMTP_PASSWORD must be supplied together."
            )
        if not self.email_notification_events:
            return self
        missing_settings = tuple(
            environment_name
            for environment_name, value in (
                (EMAIL_SMTP_HOST_ENV, self.email_smtp_host),
                (EMAIL_FROM_ENV, self.email_from),
                (EMAIL_TO_ENV, self.email_to),
            )
            if not value
        )
        if missing_settings:
            missing = ", ".join(missing_settings)
            raise ValueError(
                f"{missing} must be supplied when {EMAIL_NOTIFICATION_EVENTS_ENV} is set."
            )
        return self


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
                EMAIL_NOTIFICATION_EVENTS_ENV: environment.get(
                    EMAIL_NOTIFICATION_EVENTS_ENV,
                ),
                EMAIL_SMTP_HOST_ENV: environment.get(EMAIL_SMTP_HOST_ENV),
                EMAIL_SMTP_PORT_ENV: environment.get(
                    EMAIL_SMTP_PORT_ENV,
                    DEFAULT_EMAIL_SMTP_PORT,
                ),
                EMAIL_SMTP_SECURITY_ENV: environment.get(
                    EMAIL_SMTP_SECURITY_ENV,
                    EmailSmtpSecurity.STARTTLS.value,
                ),
                EMAIL_SMTP_USERNAME_ENV: environment.get(EMAIL_SMTP_USERNAME_ENV),
                EMAIL_SMTP_PASSWORD_ENV: environment.get(EMAIL_SMTP_PASSWORD_ENV),
                EMAIL_FROM_ENV: environment.get(EMAIL_FROM_ENV),
                EMAIL_TO_ENV: environment.get(EMAIL_TO_ENV),
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


def _comma_separated_values(value: object, setting_name: str) -> tuple[str, ...]:
    """Parse a non-empty comma-separated dotenv value with trimmed entries."""

    if not isinstance(value, str):
        raise TypeError(f"{setting_name} must be a comma-separated string.")
    values = tuple(item.strip() for item in value.split(","))
    if not values or any(not item for item in values):
        raise ValueError(f"{setting_name} must not contain empty entries.")
    return values


def _tcp_port(value: object, setting_name: str) -> int:
    """Parse one conventional valid TCP port from a dotenv scalar."""

    message = f"{setting_name} must be an integer between 1 and 65535."
    if isinstance(value, bool):
        raise TypeError(message)
    if isinstance(value, int):
        port = value
    elif isinstance(value, str):
        try:
            port = int(value)
        except ValueError as error:
            raise ValueError(message) from error
    else:
        raise TypeError(message)
    if not 1 <= port <= 65_535:
        raise ValueError(message)
    return port


def _is_mailbox_address(value: str) -> bool:
    """Whether a value is one header-safe bare mailbox address."""

    if not value or any(
        not character.isprintable() or character.isspace() for character in value
    ):
        return False
    try:
        return Address(addr_spec=value).addr_spec == value
    except HeaderParseError, ValueError:
        return False
