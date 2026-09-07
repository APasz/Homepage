"""Cached GitHub profile enrichment for public link cards."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from datetime import timedelta
from time import monotonic
from typing import Final, cast
from urllib.parse import quote

import httpx

from apasz_hub.data import CardKind, LinkCard

GITHUB_API_BASE_URL: Final = "https://api.github.com/users"
GITHUB_REPOSITORY_CACHE_TTL: Final = timedelta(hours=18)
GITHUB_REQUEST_TIMEOUT_SECONDS: Final = 3.0
GITHUB_REQUEST_HEADERS: Final = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "APasz-Hub",
}

type GithubRepositoryCountFetcher = Callable[[str], Awaitable[int]]
type MonotonicClock = Callable[[], float]


class GithubRepositoryCountUnavailable(RuntimeError):
    """Raised when GitHub cannot provide a valid public repository count."""


@dataclass(frozen=True, slots=True)
class _CachedRepositoryCount:
    """One cached count, including temporary failures without a prior value."""

    value: int | None
    expires_at: float


class GithubRepositoryCountCache:
    """Cache public repository counts and preserve the last successful result."""

    def __init__(
        self,
        fetch_count: GithubRepositoryCountFetcher,
        *,
        ttl: timedelta = GITHUB_REPOSITORY_CACHE_TTL,
        clock: MonotonicClock = monotonic,
    ) -> None:
        if ttl <= timedelta():
            raise ValueError("GitHub repository cache TTL must be positive.")
        self._fetch_count = fetch_count
        self._ttl_seconds = ttl.total_seconds()
        self._clock = clock
        self._entries: dict[str, _CachedRepositoryCount] = {}
        self._refresh_lock = asyncio.Lock()

    async def get(self, login: str) -> int | None:
        """Return a fresh or stale count, suppressing GitHub availability failures."""

        cache_key = login.strip().casefold()
        if not cache_key:
            raise ValueError("GitHub login must not be empty.")
        now = self._clock()
        cached = self._entries.get(cache_key)
        if cached is not None and cached.expires_at > now:
            return cached.value

        async with self._refresh_lock:
            now = self._clock()
            cached = self._entries.get(cache_key)
            if cached is not None and cached.expires_at > now:
                return cached.value
            try:
                value = await self._fetch_count(cache_key)
            except GithubRepositoryCountUnavailable:
                value = cached.value if cached is not None else None
            else:
                value = _validated_repository_count(value)
            self._entries[cache_key] = _CachedRepositoryCount(
                value=value,
                expires_at=now + self._ttl_seconds,
            )
            return value


async def fetch_public_repository_count(login: str) -> int:
    """Fetch GitHub's public repository count for one profile login."""

    endpoint = f"{GITHUB_API_BASE_URL}/{quote(login, safe='')}"
    try:
        async with httpx.AsyncClient(
            headers=GITHUB_REQUEST_HEADERS,
            timeout=GITHUB_REQUEST_TIMEOUT_SECONDS,
        ) as client:
            response = await client.get(endpoint)
            response.raise_for_status()
            payload = cast(object, response.json())
    except (httpx.HTTPError, ValueError) as error:
        raise GithubRepositoryCountUnavailable(
            f"Unable to fetch GitHub repository count for {login}."
        ) from error
    return _public_repository_count(payload)


async def enrich_github_metadata(
    cards: tuple[LinkCard, ...],
    repository_counts: GithubRepositoryCountCache,
) -> tuple[LinkCard, ...]:
    """Replace GitHub card metadata with cached public repository counts."""

    enriched_cards: list[LinkCard] = []
    for card in cards:
        if card.schema is not CardKind.GITHUB:
            enriched_cards.append(card)
            continue
        repository_count = await repository_counts.get(card.github_login)
        if repository_count is None:
            enriched_cards.append(card)
            continue
        enriched_cards.append(
            replace(card, metadata=_repository_count_metadata(repository_count))
        )
    return tuple(enriched_cards)


def _public_repository_count(payload: object) -> int:
    """Extract and validate ``public_repos`` from a GitHub user response."""

    if not isinstance(payload, dict):
        raise GithubRepositoryCountUnavailable(
            "GitHub returned a non-object profile response."
        )
    fields = cast(dict[str, object], payload)
    value = fields.get("public_repos")
    try:
        return _validated_repository_count(value)
    except ValueError as error:
        raise GithubRepositoryCountUnavailable(
            "GitHub returned an invalid public repository count."
        ) from error


def _validated_repository_count(value: object) -> int:
    """Reject malformed counts before they enter the cache or page metadata."""

    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise ValueError("GitHub repository counts must be non-negative integers.")
    return value


def _repository_count_metadata(repository_count: int) -> str:
    """Format a public repository count for card metadata."""

    noun = "Repository" if repository_count == 1 else "Repositories"
    return f"{repository_count} {noun}"


GITHUB_REPOSITORY_COUNTS: Final = GithubRepositoryCountCache(
    fetch_public_repository_count
)
