"""HTTP response content shared by public error handlers and routes."""

from __future__ import annotations

from collections.abc import Mapping

from apasz_hub.components import theme_color_meta
from apasz_hub.framework import PageResponse, page_response, response_header
from apasz_hub.middleware import NO_STORE_CACHE_CONTROL, SECURITY_HEADERS
from apasz_hub.pages import ErrorPageStatus, error_page
from apasz_hub.theme import ThemeColors


def error_page_response(
    colors: ThemeColors,
    status: ErrorPageStatus,
    *,
    headers: Mapping[str, str] | None = None,
) -> PageResponse:
    """Build one full, safely cached public error response."""

    additional_headers = (
        ()
        if headers is None
        else tuple(response_header(name, value) for name, value in headers.items())
    )
    return page_response(
        theme_color_meta(colors),
        *error_page(status),
        *additional_headers,
        response_header("Cache-Control", NO_STORE_CACHE_CONTROL),
        *(response_header(name, value) for name, value in SECURITY_HEADERS),
        status_code=status.value,
    )
