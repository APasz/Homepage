"""Server-entrypoint checks for development and production modes."""

from __future__ import annotations

import asyncio
import os
from typing import cast
from unittest import IsolatedAsyncioTestCase, TestCase
from unittest.mock import AsyncMock, Mock, patch

from starlette.types import Message, Scope

from apasz_hub import framework
from apasz_hub.application import STARTUP_EMAIL_DETAIL, create_application
from apasz_hub.notifications import DISABLED_EMAIL_NOTIFICATIONS
from apasz_hub.services import ApplicationServices, create_application_services
from apasz_hub.settings import EmailNotificationEvent


class ApplicationServicesTests(TestCase):
    """Keep application instances isolated from one another."""

    def test_application_service_bundles_have_independent_github_caches(self) -> None:
        first = create_application_services(
            email_notifications=DISABLED_EMAIL_NOTIFICATIONS
        )
        second = create_application_services(
            email_notifications=DISABLED_EMAIL_NOTIFICATIONS
        )

        self.assertIsNot(
            first.github_repository_counts,
            second.github_repository_counts,
        )


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
            proxy_headers=False,
            reload=True,
        )

    def test_production_server_trusts_only_loopback_proxy_headers(self) -> None:
        with (
            patch.dict(
                os.environ,
                {"PORT": "8080"},
                clear=True,
            ),
            patch.object(framework, "_serve") as serve,
        ):
            framework.serve_production("apasz_hub.production")

        serve.assert_called_once_with(
            appname="apasz_hub.production",
            host="127.0.0.1",
            port=8080,
            proxy_headers=True,
            forwarded_allow_ips="127.0.0.1",
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
        theme_color_store = Mock()
        open_graph_store = Mock()
        email_notifications = Mock()
        email_notifications.notify = AsyncMock()
        test_app = create_application(
            ApplicationServices(
                link_cards=link_card_store,
                theme_colors=theme_color_store,
                open_graph=open_graph_store,
                github_repository_counts=Mock(),
                github_repository_refresher=refresher,
                email_notifications=email_notifications,
            ),
        )

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
        lifespan = asyncio.create_task(test_app(scope, receive, send))
        await received.put({"type": "lifespan.startup"})
        await asyncio.wait_for(startup_complete.wait(), timeout=1)
        await received.put({"type": "lifespan.shutdown"})
        await asyncio.wait_for(lifespan, timeout=1)

        theme_color_store.load.assert_called_once_with()
        open_graph_store.load.assert_called_once_with()
        link_card_store.load.assert_called_once_with()
        refresher.start.assert_called_once_with()
        refresher.stop.assert_awaited_once_with()
        email_notifications.notify.assert_awaited_once_with(
            EmailNotificationEvent.STARTUP,
            STARTUP_EMAIL_DETAIL,
        )
        self.assertEqual(
            [message["type"] for message in sent],
            ["lifespan.startup.complete", "lifespan.shutdown.complete"],
        )
