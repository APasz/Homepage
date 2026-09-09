"""Controls shared by private configuration forms."""

from __future__ import annotations

from apasz_hub.config_security import CONFIG_CSRF_FORM_NAME
from apasz_hub.framework import HtmlNode, Input, Label, Span
from apasz_hub.theme import ThemeColor


def csrf_token_input(csrf_token: str) -> HtmlNode:
    """Build a configuration form's required CSRF field."""

    return Input(
        type="hidden",
        name=CONFIG_CSRF_FORM_NAME,
        value=csrf_token,
    )


def theme_color_control(color: ThemeColor) -> HtmlNode:
    """Render one accessible browser-colour input."""

    return Label(
        Span(
            Span(color.label, cls="config-colour-control__label"),
            Span(
                color.value.upper(),
                data_theme_color_value=color.token.value,
                cls="config-colour-control__value",
            ),
            cls="config-colour-control__copy",
        ),
        Input(
            type="color",
            value=color.value,
            name=color.token.value,
            data_theme_color=color.token.value,
            aria_label=f"Set {color.label} colour",
            cls="config-colour-control__input",
        ),
        cls="config-colour-control",
    )
