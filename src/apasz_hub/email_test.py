"""Command-line SMTP delivery check for configured APasz Hub email."""

from __future__ import annotations

import argparse
import smtplib
import sys
from collections.abc import Sequence

from apasz_hub.notifications import (
    EmailNotificationConfigurationError,
    email_test_service,
)
from apasz_hub.settings import SettingsValidationError, load_settings


def main(argv: Sequence[str] | None = None) -> int:
    """Send one explicit test message using the configured SMTP transport."""

    parser = argparse.ArgumentParser(
        description="Send an APasz Hub SMTP test email using the configured settings.",
    )
    parser.parse_args(argv)
    try:
        email_test_service(load_settings()).send_test_email()
    except (EmailNotificationConfigurationError, SettingsValidationError) as error:
        print(f"Email test setup failed: {error}", file=sys.stderr)
        return 2
    except OSError, smtplib.SMTPException:
        print(
            "Email test failed. Check the SMTP host, port, security mode, and credentials.",
            file=sys.stderr,
        )
        return 1

    print("Test email sent.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
