"""Checks for the explicit SMTP test-email command."""

from __future__ import annotations

import smtplib
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from unittest import TestCase
from unittest.mock import Mock, patch

from apasz_hub import email_test
from apasz_hub.notifications import EmailNotificationConfigurationError


class EmailTestCommandTests(TestCase):
    """Keep the operator-facing SMTP diagnostic direct and failure-aware."""

    def test_sends_a_test_email_and_reports_success(self) -> None:
        service = Mock()
        output = StringIO()
        with (
            patch.object(email_test, "load_settings"),
            patch.object(email_test, "email_test_service", return_value=service),
            redirect_stdout(output),
        ):
            status = email_test.main(())

        self.assertEqual(status, 0)
        service.send_test_email.assert_called_once_with()
        self.assertEqual(output.getvalue(), "Test email sent.\n")

    def test_reports_incomplete_smtp_configuration_without_sending(self) -> None:
        errors = StringIO()
        with (
            patch.object(email_test, "load_settings"),
            patch.object(
                email_test,
                "email_test_service",
                side_effect=EmailNotificationConfigurationError("SMTP is incomplete."),
            ),
            redirect_stderr(errors),
        ):
            status = email_test.main(())

        self.assertEqual(status, 2)
        self.assertIn("Email test setup failed", errors.getvalue())

    def test_reports_delivery_failures_without_exposing_smtp_details(self) -> None:
        service = Mock()
        service.send_test_email.side_effect = OSError("server detail")
        errors = StringIO()
        with (
            patch.object(email_test, "load_settings"),
            patch.object(email_test, "email_test_service", return_value=service),
            redirect_stderr(errors),
        ):
            status = email_test.main(())

        self.assertEqual(status, 1)
        self.assertIn("Email test failed.", errors.getvalue())
        self.assertNotIn("server detail", errors.getvalue())

    def test_reports_recipient_rejections_without_exposing_addresses(self) -> None:
        service = Mock()
        service.send_test_email.side_effect = smtplib.SMTPRecipientsRefused(
            {"owner@example.com": (550, b"Mailbox unavailable")}
        )
        errors = StringIO()
        with (
            patch.object(email_test, "load_settings"),
            patch.object(email_test, "email_test_service", return_value=service),
            redirect_stderr(errors),
        ):
            status = email_test.main(())

        self.assertEqual(status, 1)
        self.assertIn("Email test failed.", errors.getvalue())
        self.assertNotIn("owner@example.com", errors.getvalue())
