"""Background-refreshed GitHub profile enrichment for public link cards."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from dataclasses import replace
from datetime import timedelta
from typing import Final, cast
from urllib.parse import quote

import httpx

from apasz_hub.data import CardKind, LinkCard

GITHUB_API_BASE_URL: Final = "https://api.github.com/users"
GITHUB_REPOSITORY_REFRESH_INTERVAL: Final = timedelta(hours=18)
GITHUB_REQUEST_TIMEOUT_SECONDS: Final = 3.0
GITHUB_REQUEST_HEADERS: Final = {
    "Accept": "application/vnd.github+json",
    "User-Agent": "APasz-Hub",
}

type GithubRepositoryCountFetcher = Callable[[str], Awaitable[int]]
type LinkCardLoader = Callable[[], tuple[LinkCard, ...]]
type AsyncDelay = Callable[[float], Awaitable[None]]

LOGGER = logging.getLogger(__name__)


class GithubRepositoryCountUnavailable(RuntimeError):
    """Raised when GitHub cannot provide a valid public repository count."""


class GithubRepositoryCountCache:
    """Store public repository counts refreshed outside page rendering."""

    def __init__(self, fetch_count: GithubRepositoryCountFetcher) -> None:
        self._fetch_count = fetch_count
        self._entries: dict[str, int] = {}
        self._refresh_lock = asyncio.Lock()

    async def get(self, login: str) -> int | None:
        """Return the last background-refreshed count without making a request."""

        return self._entries.get(_github_login_key(login))

    async def refresh(self, login: str) -> int | None:
        """Refresh one count while preserving the last value on GitHub failures."""

        cache_key = _github_login_key(login)
        async with self._refresh_lock:
            try:
                value = await self._fetch_count(cache_key)
            except GithubRepositoryCountUnavailable:
                return self._entries.get(cache_key)
            value = _validated_repository_count(value)
            self._entries[cache_key] = value
            return value


class GithubRepositoryCountRefresher:
    """Periodically refresh configured GitHub profiles without HTTP page traffic."""

    def __init__(
        self,
        repository_counts: GithubRepositoryCountCache,
        load_cards: LinkCardLoader,
        *,
        interval: timedelta = GITHUB_REPOSITORY_REFRESH_INTERVAL,
        sleep: AsyncDelay = asyncio.sleep,
    ) -> None:
        if interval <= timedelta():
            raise ValueError("GitHub repository refresh interval must be positive.")
        self._repository_counts = repository_counts
        self._load_cards = load_cards
        self._interval_seconds = interval.total_seconds()
        self._sleep = sleep
        self._task: asyncio.Task[None] | None = None

    def start(self) -> None:
        """Start the periodic refresher in the current application event loop."""

        if self._task is not None:
            raise RuntimeError("GitHub repository refresher is already running.")
        self._task = asyncio.create_task(
            self._refresh_forever(),
            name="github-repository-count-refresher",
        )

    async def stop(self) -> None:
        """Cancel and await the periodic refresher during application shutdown."""

        task = self._task
        if task is None:
            return
        self._task = None
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    async def refresh(self) -> None:
        """Refresh every unique GitHub profile in the current card configuration."""

        for login in _configured_github_logins(self._load_cards()):
            await self._repository_counts.refresh(login)

    async def _refresh_forever(self) -> None:
        while True:
            try:
                await self.refresh()
            except Exception:
                LOGGER.exception(
                    "Unable to refresh configured GitHub repository counts."
                )
            await self._sleep(self._interval_seconds)


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


def _github_login_key(login: str) -> str:
    """Normalize and validate a GitHub login used as a cache key."""

    cache_key = login.strip().casefold()
    if not cache_key:
        raise ValueError("GitHub login must not be empty.")
    return cache_key


def _configured_github_logins(cards: tuple[LinkCard, ...]) -> tuple[str, ...]:
    """Return configured GitHub logins once each, preserving card order."""

    logins: dict[str, str] = {}
    for card in cards:
        if card.schema is CardKind.GITHUB:
            login = card.github_login
            logins.setdefault(_github_login_key(login), login)
    return tuple(logins.values())


GITHUB_REPOSITORY_COUNTS: Final = GithubRepositoryCountCache(
    fetch_public_repository_count
)
