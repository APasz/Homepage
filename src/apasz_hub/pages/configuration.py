"""Private configuration page compositions."""

from __future__ import annotations

from apasz_hub.components import ButtonStyle, button_class
from apasz_hub.config_security import CONFIG_PASSWORD_FORM_NAME
from apasz_hub.data import IconAsset, LinkCard
from apasz_hub.framework import (
    H1,
    H2,
    Button,
    Div,
    Form,
    Header,
    HtmlNode,
    Input,
    Label,
    Main,
    P,
    Section,
    Span,
)
from apasz_hub.routes.paths import SiteRoute
from apasz_hub.theme import ThemeColors

from .configuration_controls import csrf_token_input, theme_color_control
from .layout import site_footer
from .link_cards import link_card_manager


def configuration_page(
    colors: ThemeColors,
    cards: tuple[LinkCard, ...],
    icon_assets: tuple[IconAsset, ...],
    *,
    csrf_token: str,
    colours_saved: bool = False,
    link_cards_saved: bool = False,
    link_cards_dirty: bool = False,
    link_cards_draft_revision: int = 0,
) -> HtmlNode:
    """Build the persisted palette and in-memory LinkCard draft controls."""

    return Main(
        _header(csrf_token),
        link_card_manager(
            cards,
            colors,
            icon_assets,
            saved=link_cards_saved,
            dirty=link_cards_dirty,
            draft_revision=link_cards_draft_revision,
            csrf_token=csrf_token,
        ),
        _colour_configuration(colors, csrf_token, saved=colours_saved),
        site_footer(),
        cls="site-shell",
    )


def configuration_login_page(*, failed: bool = False) -> HtmlNode:
    """Build the password-only gateway to the private configuration editor."""

    status = "Incorrect password" if failed else "Enter the administrator password"
    return Main(
        Header(
            H1("Configuration login", cls="config-header__title"),
            cls="config-header",
        ),
        Section(
            Form(
                Section(
                    Label(
                        Span("Password", cls="link-card-control__label"),
                        Input(
                            type="password",
                            name=CONFIG_PASSWORD_FORM_NAME,
                            autocomplete="current-password",
                            maxlength="1024",
                            required="",
                            cls="link-card-control__input",
                        ),
                        cls="link-card-control",
                    ),
                    P(status, aria_live="polite", cls="config-status"),
                    cls="config-group config-login__fields",
                ),
                Div(
                    Button(
                        "Sign in",
                        type="submit",
                        cls=button_class(ButtonStyle.ALPHA),
                    ),
                    cls="config-actions config-login__actions",
                ),
                action=SiteRoute.CONFIG_LOGIN.value,
                method="post",
                cls="config-form",
            ),
            aria_label="Configuration login",
            cls="config-panel config-login",
        ),
        site_footer(),
        cls="site-shell",
    )


def _header(csrf_token: str) -> HtmlNode:
    """Render the private page heading and session exit control."""

    return Header(
        H1("Configuration", cls="config-header__title"),
        Form(
            csrf_token_input(csrf_token),
            Button(
                "Log out",
                type="submit",
                cls=button_class(ButtonStyle.BETA),
            ),
            action=SiteRoute.CONFIG_LOGOUT.value,
            method="post",
            cls="config-header__logout",
        ),
        cls="config-header",
    )


def _colour_configuration(
    colors: ThemeColors,
    csrf_token: str,
    *,
    saved: bool,
) -> HtmlNode:
    """Render the persisted shared-palette form."""

    status = "Colours saved" if saved else "Colourate"
    return Section(
        Form(
            csrf_token_input(csrf_token),
            Section(
                H2("Site colours", cls="config-group__title"),
                Div(
                    *(theme_color_control(color) for color in colors),
                    cls="config-colour-grid",
                ),
                cls="config-group",
            ),
            Div(
                P(
                    status,
                    aria_live="polite",
                    data_theme_status="",
                    cls="config-status",
                ),
                Div(
                    Button(
                        "Reset colours",
                        type="button",
                        data_theme_reset="",
                        cls=button_class(ButtonStyle.BETA),
                    ),
                    Button(
                        "Save colours",
                        type="submit",
                        cls=button_class(ButtonStyle.ALPHA),
                    ),
                    cls="action-buttons",
                ),
                cls="config-actions",
            ),
            action=SiteRoute.CONFIG_COLOURS_SAVE.value,
            enctype="application/x-www-form-urlencoded",
            method="post",
            data_theme_controls="",
            cls="config-form",
        ),
        aria_label="Colour configuration",
        cls="config-panel",
    )
