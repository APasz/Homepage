"""Tests for opt-in SMTP application notifications."""

from __future__ import annotations

import asyncio
import ssl
import threading
from email.message import EmailMessage
from types import TracebackType
from typing import Self
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, Mock, patch

from apasz_hub.notifications import (
    SMTP_TIMEOUT_SECONDS,
    TEST_EMAIL_DETAIL,
    EmailNotificationService,
    EmailNotificationSettings,
    StartupEmailNotification,
    email_test_service,
)
from apasz_hub.settings import (
    EMAIL_FROM_ENV,
    EMAIL_SMTP_HOST_ENV,
    EMAIL_TO_ENV,
    EmailNotificationEvent,
    EmailSmtpSecurity,
    load_settings,
)


class _SmtpClient:
    """Minimal SMTP double that records one notification delivery."""

    def __init__(self) -> None:
        self.starttls_context: ssl.SSLContext | None = None
        self.credentials: tuple[str, str] | None = None
        self.message: EmailMessage | None = None
        self.refused_recipients: dict[str, tuple[int, bytes]] = {}
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        exception_type: type[BaseException] | None,
        exception: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool:
        self.closed = True
        return False

    def starttls(self, *, context: ssl.SSLContext) -> None:
        self.starttls_context = context

    def login(self, username: str, password: str) -> None:
        self.credentials = (username, password)

    def send_message(self, message: EmailMessage) -> dict[str, tuple[int, bytes]]:
        self.message = message
        return self.refused_recipients


def _notification_settings(
    *,
    events: frozenset[EmailNotificationEvent] = frozenset(
        (EmailNotificationEvent.STARTUP,)
    ),
    smtp_security: EmailSmtpSecurity = EmailSmtpSecurity.STARTTLS,
) -> EmailNotificationSettings:
    """Return complete SMTP settings suitable for an isolated delivery test."""

    return EmailNotificationSettings(
        events=events,
        smtp_host="smtp.example.com",
        smtp_port=587,
        smtp_security=smtp_security,
        sender="hub@example.com",
        recipients=("owner@example.com", "backup@example.com"),
        public_origin="https://hub.example.com",
        smtp_username="smtp-user",
        smtp_password="smtp-password",
    )


class StartupEmailNotificationTests(IsolatedAsyncioTestCase):
    """Keep startup-only notification failures outside application readiness."""

    async def test_dispatcher_failure_is_logged_without_raising(self) -> None:
        dispatcher = Mock()
        notification_called = asyncio.Event()

        async def fail_notification(*_: object) -> None:
            notification_called.set()
            raise RuntimeError("SMTP unavailable")

        dispatcher.notify = AsyncMock(side_effect=fail_notification)
        notification = StartupEmailNotification()

        with self.assertLogs("apasz_hub.notifications", level="ERROR") as logs:
            notification.start(dispatcher, "The application started successfully.")
            await asyncio.wait_for(notification_called.wait(), timeout=1)
            await asyncio.sleep(0)
            await notification.stop()

        dispatcher.notify.assert_awaited_once_with(
            EmailNotificationEvent.STARTUP,
            "The application started successfully.",
        )
        self.assertIn("Unable to dispatch startup email notification", logs.output[0])


class EmailNotificationServiceTests(IsolatedAsyncioTestCase):
    """Keep SMTP delivery optional, authenticated, and isolated from application state."""

    async def test_selected_event_runs_smtp_delivery_off_the_event_loop(self) -> None:
        service = EmailNotificationService(_notification_settings())
        worker_identifiers: list[int] = []

        def record_delivery(**_: object) -> None:
            worker_identifiers.append(threading.get_ident())

        with patch.object(
            EmailNotificationService,
            "_send",
            side_effect=record_delivery,
        ) as send_in_worker:
            await service.notify(
                EmailNotificationEvent.STARTUP,
                "The application started successfully.",
            )

        send_in_worker.assert_called_once()
        worker_arguments = send_in_worker.call_args
        message = worker_arguments.kwargs["message"]
        self.assertIsInstance(message, EmailMessage)
        self.assertEqual(
            message["Subject"],
            "APasz Hub: Up and running",
        )
        self.assertEqual(
            message.get_content(),
            "The application started successfully.\n\nSite: https://hub.example.com\n",
        )
        self.assertIsInstance(worker_arguments.kwargs["tls_context"], ssl.SSLContext)
        self.assertEqual(len(worker_identifiers), 1)
        self.assertNotEqual(worker_identifiers[0], threading.get_ident())

    async def test_selected_event_sends_a_plain_text_starttls_message(self) -> None:
        client = _SmtpClient()
        service = EmailNotificationService(_notification_settings())

        with patch.object(
            EmailNotificationService,
            "_smtp_client",
            return_value=client,
        ) as open_client:
            await service.notify(
                EmailNotificationEvent.STARTUP,
                "The application started successfully.",
            )

        open_client.assert_called_once()
        tls_context = open_client.call_args.args[0]
        self.assertIsInstance(tls_context, ssl.SSLContext)
        self.assertIsNotNone(client.starttls_context)
        self.assertIs(client.starttls_context, tls_context)
        self.assertEqual(client.credentials, ("smtp-user", "smtp-password"))
        self.assertTrue(client.closed)
        message = client.message
        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message["From"], "hub@example.com")
        self.assertEqual(message["To"], "owner@example.com, backup@example.com")
        self.assertEqual(message["Subject"], "APasz Hub: Up and running")
        self.assertEqual(
            message.get_content(),
            "The application started successfully.\n\nSite: https://hub.example.com\n",
        )

    async def test_ssl_uses_implicit_tls_without_starttls(self) -> None:
        client = _SmtpClient()
        service = EmailNotificationService(
            _notification_settings(smtp_security=EmailSmtpSecurity.SSL)
        )

        with patch(
            "apasz_hub.notifications.smtplib.SMTP_SSL",
            return_value=client,
        ) as open_client:
            await service.notify(
                EmailNotificationEvent.STARTUP,
                "The application started successfully.",
            )

        open_client.assert_called_once()
        arguments = open_client.call_args
        self.assertEqual(arguments.args, ("smtp.example.com", 587))
        self.assertEqual(arguments.kwargs["timeout"], SMTP_TIMEOUT_SECONDS)
        self.assertIsInstance(arguments.kwargs["context"], ssl.SSLContext)
        self.assertIsNone(client.starttls_context)

    async def test_plaintext_smtp_does_not_create_a_tls_context(self) -> None:
        client = _SmtpClient()
        service = EmailNotificationService(
            _notification_settings(smtp_security=EmailSmtpSecurity.NONE)
        )

        with patch.object(
            EmailNotificationService,
            "_smtp_client",
            return_value=client,
        ) as open_client:
            await service.notify(
                EmailNotificationEvent.STARTUP,
                "The application started successfully.",
            )

        open_client.assert_called_once_with(None)
        self.assertIsNone(client.starttls_context)

    async def test_unselected_event_does_not_open_an_smtp_connection(self) -> None:
        service = EmailNotificationService(_notification_settings())

        with patch.object(EmailNotificationService, "_smtp_client") as open_client:
            await service.notify(
                EmailNotificationEvent.CONFIGURATION_SAVED,
                "Site colours were saved.",
            )

        open_client.assert_not_called()

    async def test_test_email_sends_even_when_no_notification_event_is_selected(
        self,
    ) -> None:
        client = _SmtpClient()
        service = EmailNotificationService(_notification_settings(events=frozenset()))

        with patch.object(
            EmailNotificationService,
            "_smtp_client",
            return_value=client,
        ) as open_client:
            service.send_test_email()

        open_client.assert_called_once()
        self.assertIsInstance(open_client.call_args.args[0], ssl.SSLContext)
        message = client.message
        self.assertIsNotNone(message)
        assert message is not None
        self.assertEqual(message["Subject"], "APasz Hub: SMTP test")
        self.assertEqual(
            message.get_content(),
            f"{TEST_EMAIL_DETAIL}\n\nSite: https://hub.example.com\n",
        )

    async def test_test_service_is_available_when_notification_events_are_unset(
        self,
    ) -> None:
        service = email_test_service(
            load_settings(
                {
                    EMAIL_SMTP_HOST_ENV: "smtp.example.com",
                    EMAIL_FROM_ENV: "hub@example.com",
                    EMAIL_TO_ENV: "owner@example.com",
                }
            )
        )

        self.assertEqual(service.settings.events, frozenset())

    async def test_partially_refused_recipients_are_reported_as_a_failure(
        self,
    ) -> None:
        client = _SmtpClient()
        client.refused_recipients["backup@example.com"] = (550, b"Mailbox unavailable")
        service = EmailNotificationService(_notification_settings())

        with (
            patch.object(
                EmailNotificationService,
                "_smtp_client",
                return_value=client,
            ),
            self.assertLogs("apasz_hub.notifications", level="ERROR") as logs,
        ):
            await service.notify(
                EmailNotificationEvent.STARTUP,
                "The application started successfully.",
            )

        self.assertIn("Unable to send email notification for startup", logs.output[0])
        self.assertIn("SMTPRecipientsRefused", logs.output[0])
        self.assertIsNone(logs.records[0].exc_info)

    async def test_delivery_failure_is_logged_without_raising(self) -> None:
        service = EmailNotificationService(_notification_settings())

        with (
            patch.object(
                EmailNotificationService,
                "_smtp_client",
                side_effect=OSError("SMTP unavailable"),
            ),
            self.assertLogs("apasz_hub.notifications", level="ERROR") as logs,
        ):
            await service.notify(
                EmailNotificationEvent.STARTUP,
                "The application started successfully.",
            )

        self.assertIn("Unable to send email notification for startup", logs.output[0])
