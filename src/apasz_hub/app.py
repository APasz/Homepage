"""ASGI entry point for the APasz public hub."""

from apasz_hub.application import create_application
from apasz_hub.services import create_application_services

app = create_application(create_application_services())

__all__ = ("app",)
