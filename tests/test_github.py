"""Behavior checks for GitHub repository-count enrichment."""

from __future__ import annotations

import asyncio
from datetime import timedelta
from unittest import IsolatedAsyncioTestCase

from apasz_hub.data import CardKind, CardTier, LinkCard
from apasz_hub.github import (
    GithubRepositoryCountCache,
    GithubRepositoryCountUnavailable,
    enrich_github_metadata,
)


class GithubRepositoryCountCacheTests(IsolatedAsyncioTestCase):
    """Keep GitHub count refreshes bounded and failure-tolerant."""

    async def test_cache_reuses_a_count_until_its_ttl_expires(self) -> None:
        calls: list[str] = []
        current_time = [0.0]

        async def fetch_count(login: str) -> int:
            calls.append(login)
            return 7

        cache = GithubRepositoryCountCache(
            fetch_count,
            ttl=timedelta(hours=18),
            clock=lambda: current_time[0],
        )

        self.assertEqual(await cache.get("APasz"), 7)
        current_time[0] += 17 * 60 * 60
        self.assertEqual(await cache.get("apasz"), 7)
        self.assertEqual(calls, ["apasz"])

        current_time[0] += 60 * 60
        self.assertEqual(await cache.get("APasz"), 7)
        self.assertEqual(calls, ["apasz", "apasz"])

    async def test_cache_keeps_a_stale_count_after_a_refresh_failure(self) -> None:
        calls = 0
        current_time = [0.0]

        async def fetch_count(_: str) -> int:
            nonlocal calls
            calls += 1
            if calls == 1:
                return 7
            raise GithubRepositoryCountUnavailable("GitHub is unavailable.")

        cache = GithubRepositoryCountCache(
            fetch_count,
            ttl=timedelta(hours=18),
            clock=lambda: current_time[0],
        )

        self.assertEqual(await cache.get("APasz"), 7)
        current_time[0] += 18 * 60 * 60
        self.assertEqual(await cache.get("APasz"), 7)
        self.assertEqual(await cache.get("APasz"), 7)
        self.assertEqual(calls, 2)

    async def test_cache_coalesces_simultaneous_refreshes(self) -> None:
        calls = 0
        started = asyncio.Event()
        release = asyncio.Event()

        async def fetch_count(_: str) -> int:
            nonlocal calls
            calls += 1
            started.set()
            await release.wait()
            return 7

        cache = GithubRepositoryCountCache(fetch_count)
        first = asyncio.create_task(cache.get("APasz"))
        await started.wait()
        second = asyncio.create_task(cache.get("apasz"))
        await asyncio.sleep(0)
        release.set()

        self.assertEqual(await asyncio.gather(first, second), [7, 7])
        self.assertEqual(calls, 1)

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

        enriched_cards = await enrich_github_metadata(
            (github_card, normal_card),
            GithubRepositoryCountCache(fetch_count),
        )

        self.assertEqual(enriched_cards[0].metadata, "1 Repository")
        self.assertEqual(enriched_cards[1].metadata, "Unchanged metadata")
        self.assertEqual(github_card.metadata, "Fallback metadata")

    async def test_enrichment_keeps_fallback_metadata_when_github_is_unavailable(
        self,
    ) -> None:
        async def fetch_count(_: str) -> int:
            raise GithubRepositoryCountUnavailable("GitHub is unavailable.")

        github_card = LinkCard(
            title="GitHub",
            href="https://github.com/APasz",
            tier=CardTier.FEATURED,
            icon="/static/icons/github.svg",
            metadata="Fallback metadata",
            schema=CardKind.GITHUB,
        )

        (enriched_card,) = await enrich_github_metadata(
            (github_card,),
            GithubRepositoryCountCache(fetch_count),
        )

        self.assertEqual(enriched_card.metadata, "Fallback metadata")
