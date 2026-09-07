"""Production server entry point for the APasz hub."""

from apasz_hub.app import app
from apasz_hub.framework import serve_production

__all__ = ("app",)


if __name__ == "__main__":
    serve_production("apasz_hub.production")
