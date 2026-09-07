"""Server-entrypoint checks for development and production modes."""

from __future__ import annotations

import os
from unittest import TestCase
from unittest.mock import patch

from apasz_hub import framework


class ServerTests(TestCase):
    """Keep development-only settings out of the production command."""

    def test_development_server_is_loopback_with_reload(self) -> None:
        with (
            patch.dict(os.environ, {"PORT": "5100"}, clear=True),
            patch.object(framework, "_serve") as serve,
        ):
            framework.serve_development("main")

        serve.assert_called_once_with(
            appname="main",
            host="127.0.0.1",
            port=5100,
            reload=True,
        )

    def test_production_server_disables_development_features(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"APASZ_HUB_HOST": "0.0.0.0", "PORT": "8080"},
                clear=True,
            ),
            patch.object(framework, "_serve") as serve,
        ):
            framework.serve_production("apasz_hub.production")

        serve.assert_called_once_with(
            appname="apasz_hub.production",
            host="0.0.0.0",
            port=8080,
            proxy_headers=False,
            reload=False,
            server_header=False,
        )

    def test_invalid_port_fails_loudly(self) -> None:
        with (
            patch.dict(os.environ, {"PORT": "not-a-port"}, clear=True),
            self.assertRaisesRegex(ValueError, "PORT must be an integer"),
        ):
            framework.serve_development("main")
