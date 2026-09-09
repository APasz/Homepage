"""Behavior checks for GitHub repository-count enrichment."""

from __future__ import annotations

import asyncio
from unittest import IsolatedAsyncioTestCase

from apasz_hub.data import CardKind, CardTier, LinkCard
from apasz_hub.github import (
    GITHUB_REPOSITORY_REFRESH_INTERVAL,
    GithubRepositoryCountCache,
    GithubRepositoryCountRefresher,
    GithubRepositoryCountUnavailable,
    enrich_github_metadata,
)


class GithubRepositoryCountTests(IsolatedAsyncioTestCase):
    """Keep GitHub refreshes independent of homepage rendering."""

    async def test_cache_reads_do_not_trigger_a_github_request(self) -> None:
        calls: list[str] = []

        async def fetch_count(login: str) -> int:
            calls.append(login)
            return 7

        cache = GithubRepositoryCountCache(fetch_count)

        self.assertIsNone(await cache.get("APasz"))
        self.assertEqual(calls, [])

        self.assertEqual(await cache.refresh("APasz"), 7)
        self.assertEqual(await cache.get("apasz"), 7)
        self.assertEqual(calls, ["apasz"])

    async def test_cache_keeps_a_stale_count_after_a_refresh_failure(self) -> None:
        calls = 0

        async def fetch_count(_: str) -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                return 7
            raise GithubRepositoryCountUnavailable("GitHub is unavailable.")

        cache = GithubRepositoryCountCache(fetch_count)

        self.assertEqual(await cache.refresh("APasz"), 7)
        self.assertEqual(await cache.refresh("APasz"), 7)
        self.assertEqual(await cache.get("APasz"), 7)
        self.assertEqual(calls, 2)

    async def test_cache_reads_the_last_value_while_a_refresh_is_running(self) -> None:
        calls = 0
        refresh_started = asyncio.Event()
        release_refresh = asyncio.Event()

        async def fetch_count(_: str) -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                return 7
            refresh_started.set()
            await release_refresh.wait()
            return 8

        cache = GithubRepositoryCountCache(fetch_count)
        self.assertEqual(await cache.refresh("APasz"), 7)

        background_refresh = asyncio.create_task(cache.refresh("APasz"))
        await refresh_started.wait()
        self.assertEqual(await cache.get("APasz"), 7)
        release_refresh.set()

        self.assertEqual(await background_refresh, 8)
        self.assertEqual(await cache.get("APasz"), 8)

    async def test_refresher_fetches_unique_configured_github_profiles(self) -> None:
        calls: list[str] = []

        async def fetch_count(login: str) -> int:
            calls.append(login)
            return 7

        github_card = LinkCard(
            title="GitHub",
            href="https://github.com/APasz",
            tier=CardTier.FEATURED,
            icon="/static/icons/github.svg",
            metadata="Fallback metadata",
            schema=CardKind.GITHUB,
        )
        duplicate_github_card = LinkCard(
            title="GitHub duplicate",
            href="https://github.com/apasz",
            tier=CardTier.STANDARD,
            icon="/static/icons/github.svg",
            schema=CardKind.GITHUB,
        )
        normal_card = LinkCard(
            title="Example",
            href="https://example.com",
            tier=CardTier.STANDARD,
            icon="/static/icons/github.svg",
        )
        cache = GithubRepositoryCountCache(fetch_count)
        refresher = GithubRepositoryCountRefresher(
            cache,
            lambda: (github_card, duplicate_github_card, normal_card),
        )

        await refresher.refresh()

        self.assertEqual(calls, ["apasz"])
        self.assertEqual(await cache.get("APasz"), 7)

    async def test_refresher_repeats_after_the_configured_interval(self) -> None:
        calls: list[str] = []
        delays: list[float] = []
        first_delay_reached = asyncio.Event()
        second_delay_reached = asyncio.Event()
        release_first_delay = asyncio.Event()

        async def fetch_count(login: str) -> int:
            calls.append(login)
            return 7

        async def sleep(delay: float) -> None:
            delays.append(delay)
            if len(delays) == 1:
                first_delay_reached.set()
                await release_first_delay.wait()
                return
            second_delay_reached.set()
            await asyncio.Event().wait()

        github_card = LinkCard(
            title="GitHub",
            href="https://github.com/APasz",
            tier=CardTier.FEATURED,
            icon="/static/icons/github.svg",
            metadata="Fallback metadata",
            schema=CardKind.GITHUB,
        )
        refresher = GithubRepositoryCountRefresher(
            GithubRepositoryCountCache(fetch_count),
            lambda: (github_card,),
            sleep=sleep,
        )

        refresher.start()
        await first_delay_reached.wait()
        release_first_delay.set()
        await second_delay_reached.wait()
        await refresher.stop()

        self.assertEqual(calls, ["apasz", "apasz"])
        self.assertEqual(
            delays,
            [
                GITHUB_REPOSITORY_REFRESH_INTERVAL.total_seconds(),
                GITHUB_REPOSITORY_REFRESH_INTERVAL.total_seconds(),
            ],
        )

    async def test_stop_cancels_an_in_flight_one_off_refresh(self) -> None:
        refresh_started = asyncio.Event()
        refresh_cancelled = asyncio.Event()

        async def fetch_count(_: str) -> int:
            refresh_started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                refresh_cancelled.set()
                raise
            return 7

        github_card = LinkCard(
            title="GitHub",
            href="https://github.com/APasz",
            tier=CardTier.FEATURED,
            icon="/static/icons/github.svg",
            metadata="Fallback metadata",
            schema=CardKind.GITHUB,
        )
        refresher = GithubRepositoryCountRefresher(
            GithubRepositoryCountCache(fetch_count),
            lambda: (github_card,),
        )

        refresher.refresh_in_background()
        try:
            await asyncio.wait_for(refresh_started.wait(), timeout=1)
        finally:
            await refresher.stop()

        self.assertTrue(refresh_cancelled.is_set())

    async def test_enrichment_replaces_only_github_card_metadata(self) -> None:
        async def fetch_count(login: str) -> int:
            self.assertEqual(login, "apasz")
            return 1

        github_card = LinkCard(
            title="GitHub",
            href="https://github.com/APasz",
            tier=CardTier.FEATURED,
            icon="/static/icons/github.svg",
            metadata="Fallback metadata",
            schema=CardKind.GITHUB,
        )
        normal_card = LinkCard(
            title="Example",
            href="https://example.com",
            tier=CardTier.STANDARD,
            icon="/static/icons/github.svg",
            metadata="Unchanged metadata",
        )

        cache = GithubRepositoryCountCache(fetch_count)
        await cache.refresh("APasz")
        enriched_cards = await enrich_github_metadata((github_card, normal_card), cache)

        self.assertEqual(enriched_cards[0].metadata, "1 Repository")
        self.assertEqual(enriched_cards[1].metadata, "Unchanged metadata")
        self.assertEqual(github_card.metadata, "Fallback metadata")

    async def test_enrichment_keeps_fallback_metadata_when_github_is_unavailable(
        self,
    ) -> None:
        calls: list[str] = []

        async def fetch_count(login: str) -> int:
            calls.append(login)
            raise GithubRepositoryCountUnavailable("GitHub is unavailable.")

        github_card = LinkCard(
            title="GitHub",
            href="https://github.com/APasz",
            tier=CardTier.FEATURED,
            icon="/static/icons/github.svg",
            metadata="Fallback metadata",
            schema=CardKind.GITHUB,
        )

        cache = GithubRepositoryCountCache(fetch_count)
        self.assertIsNone(await cache.refresh("APasz"))
        (enriched_card,) = await enrich_github_metadata((github_card,), cache)

        self.assertEqual(enriched_card.metadata, "Fallback metadata")
        self.assertEqual(calls, ["apasz"])
