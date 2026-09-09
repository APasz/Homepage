"""Application-owned stores and background services."""

from __future__ import annotations

from dataclasses import dataclass

from apasz_hub.data import LinkCardStore
from apasz_hub.github import (
    GithubRepositoryCountCache,
    GithubRepositoryCountRefresher,
    fetch_public_repository_count,
)
from apasz_hub.open_graph import OpenGraphStore
from apasz_hub.theme import ThemeColorStore


@dataclass(frozen=True, slots=True)
class ApplicationServices:
    """Stateful collaborators owned by one ASGI application instance."""

    link_cards: LinkCardStore
    theme_colors: ThemeColorStore
    open_graph: OpenGraphStore
    github_repository_counts: GithubRepositoryCountCache
    github_repository_refresher: GithubRepositoryCountRefresher


def create_application_services(
    *,
    link_cards: LinkCardStore | None = None,
    theme_colors: ThemeColorStore | None = None,
    open_graph: OpenGraphStore | None = None,
    github_repository_counts: GithubRepositoryCountCache | None = None,
) -> ApplicationServices:
    """Build a consistently wired set of application-owned services."""

    card_store = LinkCardStore() if link_cards is None else link_cards
    color_store = ThemeColorStore() if theme_colors is None else theme_colors
    open_graph_store = OpenGraphStore() if open_graph is None else open_graph
    repository_counts = (
        GithubRepositoryCountCache(fetch_public_repository_count)
        if github_repository_counts is None
        else github_repository_counts
    )
    return ApplicationServices(
        link_cards=card_store,
        theme_colors=color_store,
        open_graph=open_graph_store,
        github_repository_counts=repository_counts,
        github_repository_refresher=GithubRepositoryCountRefresher(
            repository_counts,
            card_store.published_cards,
        ),
    )
