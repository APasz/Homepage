"""Opt-in SMTP notifications for noteworthy application events."""

from __future__ import annotations

import asyncio
import logging
import smtplib
import ssl
from collections.abc import Mapping
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from email.message import EmailMessage
from functools import partial
from typing import Final, Protocol

from apasz_hub.settings import (
    ApplicationSettings,
    EmailNotificationEvent,
    EmailSmtpSecurity,
)

SMTP_TIMEOUT_SECONDS: Final = 10.0
SMTP_WORKER_COUNT: Final = 2
EMAIL_SUBJECT_PREFIX: Final = "APasz Hub"
TEST_EMAIL_SUBJECT: Final = "SMTP test"
TEST_EMAIL_DETAIL: Final = "Hey, this is a test email from APasz Hub. SMTP is working."
EVENT_SUBJECTS: Final[Mapping[EmailNotificationEvent, str]] = {
    EmailNotificationEvent.STARTUP: "Up and running",
    EmailNotificationEvent.CONFIGURATION_SAVED: "Settings saved",
}
LOGGER = logging.getLogger(__name__)
_SMTP_EXECUTOR: Final = ThreadPoolExecutor(
    max_workers=SMTP_WORKER_COUNT,
    thread_name_prefix="apasz-smtp",
)


class EmailNotificationDispatcher(Protocol):
    """Deliver one typed application event to its configured destinations."""

    async def notify(self, event: EmailNotificationEvent, detail: str) -> None:
        """Deliver a notification for an application event."""


class EmailNotificationConfigurationError(ValueError):
    """Raised when required SMTP settings are incomplete."""


@dataclass(frozen=True, slots=True)
class EmailNotificationSettings:
    """The complete SMTP configuration used to deliver application email."""

    events: frozenset[EmailNotificationEvent]
    smtp_host: str
    smtp_port: int
    smtp_security: EmailSmtpSecurity
    sender: str
    recipients: tuple[str, ...]
    public_origin: str
    smtp_username: str | None = None
    smtp_password: str | None = field(default=None, repr=False)


class DisabledEmailNotificationService:
    """Avoid work when a deployment has not opted into email notifications."""

    async def notify(self, event: EmailNotificationEvent, detail: str) -> None:
        """Deliberately discard events while notification delivery is disabled."""


DISABLED_EMAIL_NOTIFICATIONS: Final[EmailNotificationDispatcher] = (
    DisabledEmailNotificationService()
)


@dataclass(frozen=True, slots=True)
class EmailNotificationService:
    """Deliver selected notifications through one authenticated SMTP endpoint."""

    settings: EmailNotificationSettings

    async def notify(self, event: EmailNotificationEvent, detail: str) -> None:
        """Send a selected event without allowing delivery failures to alter state."""

        if event not in self.settings.events:
            return
        try:
            message = self._message(
                subject=EVENT_SUBJECTS[event],
                detail=detail,
            )
            tls_context = self._tls_context()
            await asyncio.get_running_loop().run_in_executor(
                _SMTP_EXECUTOR,
                partial(
                    self._send,
                    message=message,
                    tls_context=tls_context,
                ),
            )
        except (OSError, smtplib.SMTPException) as error:
            LOGGER.error(
                "Unable to send email notification for %s (%s).",
                event.value,
                type(error).__name__,
            )

    def send_test_email(self) -> None:
        """Send one SMTP test message, allowing failures to reach the caller."""

        self._send(
            message=self._message(
                subject=TEST_EMAIL_SUBJECT,
                detail=TEST_EMAIL_DETAIL,
            ),
            tls_context=self._tls_context(),
        )

    def _send(
        self,
        *,
        message: EmailMessage,
        tls_context: ssl.SSLContext | None,
    ) -> None:
        """Deliver one prepared message on a bounded synchronous SMTP connection."""

        with self._smtp_client(tls_context) as client:
            if self.settings.smtp_security is EmailSmtpSecurity.STARTTLS:
                client.starttls(context=_required_tls_context(tls_context))
            if self.settings.smtp_username is not None:
                password = self.settings.smtp_password
                if password is None:
                    raise EmailNotificationConfigurationError(
                        "SMTP credentials are incomplete."
                    )
                client.login(self.settings.smtp_username, password)
            refused_recipients = client.send_message(message)
        if refused_recipients:
            raise smtplib.SMTPRecipientsRefused(refused_recipients)

    def _tls_context(self) -> ssl.SSLContext | None:
        """Create a TLS context before scheduling blocking SMTP work."""

        if self.settings.smtp_security is EmailSmtpSecurity.NONE:
            return None
        return ssl.create_default_context()

    def _smtp_client(self, tls_context: ssl.SSLContext | None) -> smtplib.SMTP:
        """Open the selected secure or plaintext SMTP transport."""

        if self.settings.smtp_security is EmailSmtpSecurity.SSL:
            return smtplib.SMTP_SSL(
                self.settings.smtp_host,
                self.settings.smtp_port,
                timeout=SMTP_TIMEOUT_SECONDS,
                context=_required_tls_context(tls_context),
            )
        return smtplib.SMTP(
            self.settings.smtp_host,
            self.settings.smtp_port,
            timeout=SMTP_TIMEOUT_SECONDS,
        )

    def _message(
        self,
        *,
        subject: str,
        detail: str,
    ) -> EmailMessage:
        """Build a plain-text message with a compact site footer."""

        message = EmailMessage()
        message["From"] = self.settings.sender
        message["To"] = ", ".join(self.settings.recipients)
        message["Subject"] = f"{EMAIL_SUBJECT_PREFIX}: {subject}"
        message.set_content(
            "\n".join(
                (
                    detail,
                    "",
                    f"Site: {self.settings.public_origin}",
                )
            )
        )
        return message


def _required_tls_context(tls_context: ssl.SSLContext | None) -> ssl.SSLContext:
    """Return the context required by an explicitly TLS-enabled transport."""

    if tls_context is None:
        raise RuntimeError("TLS context is required for the selected SMTP security.")
    return tls_context


def email_notification_service(
    application_settings: ApplicationSettings,
) -> EmailNotificationDispatcher:
    """Build a configured dispatcher, or an allocation-free disabled dispatcher."""

    if not application_settings.email_notification_events:
        return DISABLED_EMAIL_NOTIFICATIONS
    return EmailNotificationService(_email_notification_settings(application_settings))


def email_test_service(
    application_settings: ApplicationSettings,
) -> EmailNotificationService:
    """Build an SMTP service for a one-off test, even when events are disabled."""

    return EmailNotificationService(_email_notification_settings(application_settings))


def _email_notification_settings(
    application_settings: ApplicationSettings,
) -> EmailNotificationSettings:
    """Extract validated SMTP delivery settings or report the missing requirements."""

    smtp_host = application_settings.email_smtp_host
    sender = application_settings.email_from
    recipients = application_settings.email_to
    if smtp_host is None or sender is None or not recipients:
        raise EmailNotificationConfigurationError(
            "EMAIL_SMTP_HOST, EMAIL_FROM, and EMAIL_TO must be configured."
        )
    smtp_password_secret = application_settings.email_smtp_password
    smtp_password = (
        None
        if smtp_password_secret is None
        else smtp_password_secret.get_secret_value()
    )
    if (application_settings.email_smtp_username is None) != (smtp_password is None):
        raise EmailNotificationConfigurationError(
            "EMAIL_SMTP_USERNAME and EMAIL_SMTP_PASSWORD must be configured together."
        )
    return EmailNotificationSettings(
        events=application_settings.email_notification_events,
        smtp_host=smtp_host,
        smtp_port=application_settings.email_smtp_port,
        smtp_security=application_settings.email_smtp_security,
        sender=sender,
        recipients=recipients,
        public_origin=application_settings.public_origin,
        smtp_username=application_settings.email_smtp_username,
        smtp_password=smtp_password,
    )
