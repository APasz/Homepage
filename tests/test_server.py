"""Server-entrypoint checks for development and production modes."""

from __future__ import annotations

import asyncio
import os
from typing import cast
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from starlette.types import Message, Scope

import apasz_hub.app as application
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
                {"HOST": "0.0.0.0", "PORT": "8080"},
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


class AppLifecycleTests(IsolatedAsyncioTestCase):
    """Keep the GitHub refresher attached to the ASGI application lifecycle."""

    async def test_lifespan_starts_and_stops_the_github_refresher(self) -> None:
        received: asyncio.Queue[Message] = asyncio.Queue()
        sent: list[Message] = []
        startup_complete = asyncio.Event()
        refresher = Mock()
        refresher.stop = AsyncMock()
        link_card_store = Mock()

        async def receive() -> Message:
            return await received.get()

        async def send(message: Message) -> None:
            sent.append(message)
            if message["type"] == "lifespan.startup.complete":
                startup_complete.set()

        scope = cast(
            Scope,
            {
                "type": "lifespan",
                "asgi": {"version": "3.0", "spec_version": "2.0"},
                "state": {},
            },
        )
        with (
            patch.object(application, "LINK_CARD_STORE", link_card_store),
            patch.object(application, "GITHUB_REPOSITORY_REFRESHER", refresher),
        ):
            lifespan = asyncio.create_task(application.app(scope, receive, send))
            await received.put({"type": "lifespan.startup"})
            await asyncio.wait_for(startup_complete.wait(), timeout=1)
            await received.put({"type": "lifespan.shutdown"})
            await asyncio.wait_for(lifespan, timeout=1)

        link_card_store.load.assert_called_once_with()
        refresher.start.assert_called_once_with()
        refresher.stop.assert_awaited_once_with()
        self.assertEqual(
            [message["type"] for message in sent],
            ["lifespan.startup.complete", "lifespan.shutdown.complete"],
        )
