"""FastHTML application assembly for the APasz public hub."""

from __future__ import annotations

from pathlib import Path
from typing import Final

from apasz_hub.components import document_headers
from apasz_hub.data import SITE, load_link_cards
from apasz_hub.framework import HtmlNode, create_app, mount_static_files
from apasz_hub.github import (
    GITHUB_REPOSITORY_COUNTS,
    GithubRepositoryCountRefresher,
)
from apasz_hub.middleware import PublicSiteHeadersMiddleware
from apasz_hub.pages import homepage

STATIC_DIRECTORY = Path(__file__).parent / "static"
GITHUB_REPOSITORY_REFRESHER: Final = GithubRepositoryCountRefresher(
    GITHUB_REPOSITORY_COUNTS,
    load_link_cards,
)


async def _start_github_repository_refresher() -> None:
    """Begin refreshing GitHub card metadata independently of page visits."""

    GITHUB_REPOSITORY_REFRESHER.start()


async def _stop_github_repository_refresher() -> None:
    """Stop the GitHub refresher before the application event loop closes."""

    await GITHUB_REPOSITORY_REFRESHER.stop()


app = create_app(
    title=SITE.title,
    headers=document_headers(),
    on_startup=_start_github_repository_refresher,
    on_shutdown=_stop_github_repository_refresher,
)
app.add_middleware(PublicSiteHeadersMiddleware)
mount_static_files(app, path="/static", directory=STATIC_DIRECTORY)


@app.get("/")
async def home() -> HtmlNode:
    """Render the public hub."""

    return await homepage()
