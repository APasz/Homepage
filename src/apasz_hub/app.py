"""FastHTML application assembly for the APasz public hub."""

from __future__ import annotations

from pathlib import Path

from apasz_hub.components import document_headers
from apasz_hub.data import SITE
from apasz_hub.framework import HtmlNode, create_app, mount_static_files
from apasz_hub.middleware import PublicSiteHeadersMiddleware
from apasz_hub.pages import homepage

STATIC_DIRECTORY = Path(__file__).parent / "static"

app = create_app(title=SITE.title, headers=document_headers())
app.add_middleware(PublicSiteHeadersMiddleware)
mount_static_files(app, path="/static", directory=STATIC_DIRECTORY)


@app.get("/")
async def home() -> HtmlNode:
    """Render the public hub."""

    return await homepage()
