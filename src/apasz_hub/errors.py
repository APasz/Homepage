"""HTTP response content shared by public error handlers and routes."""

from __future__ import annotations

from collections.abc import Mapping

from apasz_hub.components import document_metadata, theme_color_meta
from apasz_hub.data import SITE, SiteMetadata
from apasz_hub.framework import PageResponse, page_response, response_header
from apasz_hub.middleware import NO_STORE_CACHE_CONTROL, SECURITY_HEADERS
from apasz_hub.pages import ErrorPageStatus, error_page
from apasz_hub.theme import ThemeColors


def error_page_response(
    colors: ThemeColors,
    status: ErrorPageStatus,
    *,
    metadata: SiteMetadata = SITE,
    headers: Mapping[str, str] | None = None,
) -> PageResponse:
    """Build one full, safely cached public error response."""

    additional_headers = (
        ()
        if headers is None
        else tuple(response_header(name, value) for name, value in headers.items())
    )
    return page_response(
        *document_metadata(metadata, include_title=False),
        theme_color_meta(colors),
        *error_page(status, site_title=metadata.title),
        *additional_headers,
        response_header("Cache-Control", NO_STORE_CACHE_CONTROL),
        *(response_header(name, value) for name, value in SECURITY_HEADERS),
        status_code=status.value,
    )
