"""Application-owned stores and background services."""

from __future__ import annotations

from dataclasses import dataclass

from apasz_hub.data import LinkCardStore
from apasz_hub.github import (
    GithubRepositoryCountCache,
    GithubRepositoryCountRefresher,
    fetch_public_repository_count,
)
from apasz_hub.theme import ThemeColorStore


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """Stateful collaborators owned by one ASGI application instance."""

    link_cards: LinkCardStore
    theme_colors: ThemeColorStore
    github_repository_counts: GithubRepositoryCountCache
    github_repository_refresher: GithubRepositoryCountRefresher


def create_application_services(
    *,
    link_cards: LinkCardStore | None = None,
    theme_colors: ThemeColorStore | None = None,
    github_repository_counts: GithubRepositoryCountCache | None = None,
) -> ApplicationServices:
    """Build a consistently wired set of application-owned services."""

    card_store = LinkCardStore() if link_cards is None else link_cards
    color_store = ThemeColorStore() if theme_colors is None else theme_colors
    repository_counts = (
        GithubRepositoryCountCache(fetch_public_repository_count)
        if github_repository_counts is None
        else github_repository_counts
    )
    return ApplicationServices(
        link_cards=card_store,
        theme_colors=color_store,
        github_repository_counts=repository_counts,
        github_repository_refresher=GithubRepositoryCountRefresher(
            repository_counts,
            card_store.published_cards,
        ),
    )
