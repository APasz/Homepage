"""Server-rendered page compositions for the APasz hub."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from apasz_hub.components import ButtonStyle, button_class, link_card, utility_link
from apasz_hub.config_security import (
    CONFIG_CSRF_FORM_NAME,
    CONFIG_PASSWORD_FORM_NAME,
)
from apasz_hub.data import (
    LINK_CARD_COLOUR_CONTROL_PAIRS,
    LINK_CARD_DELETE_INDEX_FORM_NAME,
    LINK_CARD_DESTINATION_SPECS,
    PROFILE_IMAGE_URL,
    PROFILE_REDUCED_MOTION_IMAGE_URL,
    WORDMARK_URL,
    CardKind,
    CardTier,
    IconAsset,
    LinkCard,
    LinkCardColourControl,
    LinkCardColourControlPair,
    LinkCardFormField,
    cards_for_tier,
    link_card_colour_override,
    link_card_form_destination,
    link_card_form_name,
)
from apasz_hub.framework import (
    H1,
    H2,
    A,
    Button,
    Details,
    Dialog,
    Div,
    Footer,
    Form,
    Header,
    HtmlNode,
    Img,
    Input,
    Label,
    Li,
    Main,
    Nav,
    Option,
    P,
    Picture,
    Section,
    Select,
    Source,
    Span,
    Summary,
    Textarea,
    Ul,
)
from apasz_hub.github import (
    GithubRepositoryCountCache,
    enrich_github_metadata,
)
from apasz_hub.routes.paths import SiteRoute
from apasz_hub.theme import ThemeColor, ThemeColors, theme_color

_SITE_NAVIGATION: Final[tuple[tuple[SiteRoute, str], ...]] = ((SiteRoute.HOME, "Home"),)


async def homepage(
    cards: tuple[LinkCard, ...],
    repository_counts: GithubRepositoryCountCache,
) -> HtmlNode:
    """Build the small, single-page public APasz hub."""

    cards = await enrich_github_metadata(cards, repository_counts)
    return Main(
        Header(
            Div(
                Picture(
                    Source(
                        media="(prefers-reduced-motion: reduce)",
                        srcset=PROFILE_REDUCED_MOTION_IMAGE_URL,
                        type="image/webp",
                    ),
                    Img(
                        src=PROFILE_IMAGE_URL,
                        alt="",
                        aria_hidden="true",
                        cls="profile-image",
                    ),
                    cls="profile-image-frame",
                ),
                H1(
                    Span("APasz", cls="wordmark__label"),
                    cls="wordmark",
                    style=f"--wordmark-source: url({WORDMARK_URL})",
                ),
                cls="wordmark-lockup",
            ),
            cls="site-header",
        ),
        _card_section(cards, CardTier.FEATURED, "Primary links"),
        _card_section(cards, CardTier.STANDARD, "Other public links"),
        Section(
            Nav(
                *(
                    utility_link(card)
                    for card in cards_for_tier(cards, CardTier.UTILITY)
                ),
                aria_label="Utility links",
                cls="utility-grid",
            ),
            cls="hub-section hub-section--utilities",
        ),
        _site_footer(SiteRoute.HOME),
        cls="site-shell",
    )


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

    colour_status = "Colours saved" if colours_saved else "Colourate"

    return Main(
        Header(
            H1("Configuration", cls="config-header__title"),
            Form(
                Input(
                    type="hidden",
                    name=CONFIG_CSRF_FORM_NAME,
                    value=csrf_token,
                ),
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
        ),
        _link_card_manager(
            cards,
            colors,
            icon_assets,
            saved=link_cards_saved,
            dirty=link_cards_dirty,
            draft_revision=link_cards_draft_revision,
            csrf_token=csrf_token,
        ),
        Section(
            Form(
                Input(
                    type="hidden",
                    name=CONFIG_CSRF_FORM_NAME,
                    value=csrf_token,
                ),
                Section(
                    H2("Site colours", cls="config-group__title"),
                    Div(
                        *(_theme_color_control(color) for color in colors),
                        cls="config-colour-grid",
                    ),
                    cls="config-group",
                ),
                Div(
                    P(
                        colour_status,
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
        ),
        _site_footer(),
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
        _site_footer(),
        cls="site-shell",
    )


def _card_section(cards: tuple[LinkCard, ...], tier: CardTier, label: str) -> HtmlNode:
    """Render a card tier as a labelled grid."""

    return Section(
        Div(
            *(link_card(card) for card in cards_for_tier(cards, tier)),
            cls=f"link-grid link-grid--{tier.value}",
        ),
        aria_label=label,
        cls="hub-section",
    )


def _theme_color_control(color: ThemeColor) -> HtmlNode:
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


def _link_card_manager(
    cards: tuple[LinkCard, ...],
    colors: ThemeColors,
    icon_assets: tuple[IconAsset, ...],
    *,
    saved: bool,
    dirty: bool,
    draft_revision: int,
    csrf_token: str,
) -> HtmlNode:
    """Render expandable controls for the in-memory LinkCard draft."""

    if saved:
        status = "Link cards saved"
    elif dirty:
        status = "Draft changes"
    else:
        status = "Linkerate"
    return Section(
        Div(
            H2("Link cards", cls="link-card-manager__title"),
            cls="link-card-manager__header",
        ),
        Form(
            Input(
                type="hidden",
                name=CONFIG_CSRF_FORM_NAME,
                value=csrf_token,
            ),
            Div(
                *(
                    _link_card_manager_card(card, index, colors)
                    for index, card in enumerate(cards)
                ),
                cls="link-card-manager__list",
            ),
            Div(
                P(
                    status,
                    aria_live="polite",
                    data_link_card_status="",
                    cls="link-card-status",
                ),
                Div(
                    Button(
                        "Add Link",
                        type="submit",
                        formaction=SiteRoute.CONFIG_LINK_CARDS_ADD.value,
                        data_link_card_add="",
                        cls=button_class(ButtonStyle.BETA),
                    ),
                    Button(
                        "Save Links",
                        type="submit",
                        cls=button_class(ButtonStyle.ALPHA),
                    ),
                    cls="action-buttons",
                ),
                cls="link-card-actions",
            ),
            action=SiteRoute.CONFIG_LINK_CARDS_SAVE.value,
            data_link_card_controls="",
            data_link_card_draft_url=SiteRoute.CONFIG_LINK_CARDS_DRAFT.value,
            data_link_card_draft_revision=str(draft_revision),
            enctype="application/x-www-form-urlencoded",
            method="post",
        ),
        _icon_picker_dialog(icon_assets),
        aria_label="Link card management",
        cls="link-card-manager",
    )


def _icon_picker_dialog(icon_assets: tuple[IconAsset, ...]) -> HtmlNode:
    """Render the shared SVG icon picker used by every LinkCard editor."""

    options: tuple[HtmlNode, ...] = tuple(
        Button(
            Img(src=icon.url, alt="", aria_hidden="true", cls="icon-picker__image"),
            Span(icon.name, cls="icon-picker__name"),
            type="button",
            aria_label=f"Select {icon.name}",
            aria_pressed="false",
            data_icon_picker_option=icon.url,
            cls="icon-picker__option",
        )
        for icon in icon_assets
    )
    contents = options or (P("No SVG icons are available.", cls="icon-picker__empty"),)
    return Dialog(
        Div(
            H2("Choose an icon", id="icon-picker-title", cls="icon-picker__title"),
            Form(
                Button("Close", type="submit", cls="icon-picker__close"),
                method="dialog",
                cls="icon-picker__close-form",
            ),
            cls="icon-picker__header",
        ),
        Div(*contents, cls="icon-picker__grid"),
        aria_labelledby="icon-picker-title",
        aria_modal="true",
        data_icon_picker_dialog="",
        cls="icon-picker",
    )


def _link_card_manager_card(
    card: LinkCard,
    index: int,
    colors: ThemeColors,
) -> HtmlNode:
    """Render one editable LinkCard panel with native disclosure behavior."""

    return Details(
        Summary(
            Span(
                card.title,
                data_link_card_summary=LinkCardFormField.TITLE.value,
                cls="link-card-manager__card-title",
            ),
            Span(
                Span(
                    card.tier.value,
                    data_link_card_summary=LinkCardFormField.TIER.value,
                    cls="link-card-manager__tier",
                ),
                Span(
                    card.schema.value,
                    data_link_card_summary=LinkCardFormField.SCHEMA.value,
                    cls="link-card-manager__schema",
                ),
                Button(
                    "Delete",
                    type="submit",
                    formaction=SiteRoute.CONFIG_LINK_CARDS_DELETE.value,
                    formnovalidate="",
                    name=LINK_CARD_DELETE_INDEX_FORM_NAME,
                    value=str(index),
                    aria_label=f"Delete {card.title}",
                    data_link_card_delete="",
                    cls="link-card-manager__delete",
                ),
                cls="link-card-manager__meta",
            ),
            cls="link-card-manager__summary",
        ),
        _link_card_control_panel(card, index, colors),
        data_link_card_index=str(index),
        cls="link-card-manager__card",
    )


def _link_card_control_panel(
    card: LinkCard,
    index: int,
    colors: ThemeColors,
) -> HtmlNode:
    """Render schema-aware editable fields for one LinkCard draft entry."""

    return Div(
        _link_card_select_control(
            index,
            LinkCardFormField.SCHEMA,
            "Schema",
            CardKind,
            card.schema,
        ),
        *(_link_card_destination_control(card, index, schema) for schema in CardKind),
        _link_card_input_control(
            index,
            LinkCardFormField.TITLE,
            "Title",
            card.title,
        ),
        _link_card_select_control(
            index,
            LinkCardFormField.TIER,
            "Tier",
            CardTier,
            card.tier,
        ),
        _link_card_icon_control(card, index),
        _link_card_input_control(
            index,
            LinkCardFormField.ICON_SCALE,
            "Icon scale (%)",
            str(card.icon_scale),
            input_type="number",
            minimum="1",
        ),
        *(
            _link_card_colour_pair(card, index, pair, colors)
            for pair in LINK_CARD_COLOUR_CONTROL_PAIRS
        ),
        _link_card_input_control(
            index,
            LinkCardFormField.COPY_TEXT,
            "Copy value",
            card.copy_text or "",
        ),
        _link_card_textarea_control(
            index,
            LinkCardFormField.DESCRIPTION,
            "Description",
            card.description or "",
        ),
        _link_card_textarea_control(
            index,
            LinkCardFormField.METADATA,
            "Metadata",
            card.metadata or "",
        ),
        Div(
            _link_card_toggle_control(
                index,
                LinkCardFormField.OPENS_IN_NEW_TAB,
                "Open in a new tab",
                card.opens_in_new_tab,
            ),
            _link_card_toggle_control(
                index,
                LinkCardFormField.COPY_TO_CLIPBOARD,
                "Copy to clipboard",
                card.copy_to_clipboard,
            ),
            cls="link-card-toggle-pair",
        ),
        cls="link-card-panel",
    )


def _link_card_input_control(
    index: int,
    field: LinkCardFormField,
    label: str,
    value: str,
    *,
    input_type: str = "text",
    minimum: str | None = None,
    extra_input_attributes: Mapping[str, str] | None = None,
    extra_control_attributes: Mapping[str, str] | None = None,
) -> HtmlNode:
    """Render one labelled single-line LinkCard editor control."""

    attributes = _link_card_control_attributes(index, field)
    attributes.update(
        {
            "type": input_type,
            "value": value,
            "cls": "link-card-control__input",
        }
    )
    if minimum is not None:
        attributes["min"] = minimum
    if extra_input_attributes is not None:
        attributes.update(extra_input_attributes)
    control_attributes = {"cls": "link-card-control"}
    if extra_control_attributes is not None:
        control_attributes.update(extra_control_attributes)
    return Label(
        Span(label, cls="link-card-control__label"),
        Input(**attributes),
        **control_attributes,
    )


def _link_card_destination_control(
    card: LinkCard,
    index: int,
    schema: CardKind,
) -> HtmlNode:
    """Render one schema-specific destination input for a LinkCard editor."""

    spec = LINK_CARD_DESTINATION_SPECS[schema]
    input_attributes = {
        "autocomplete": spec.autocomplete,
        "placeholder": spec.placeholder,
        "required": "",
        "spellcheck": "false",
    }
    if spec.pattern is not None:
        input_attributes["pattern"] = spec.pattern
    control_attributes = {"data_link_card_destination_schema": schema.value}
    if schema is not card.schema:
        input_attributes["disabled"] = ""
        control_attributes["hidden"] = ""
    return _link_card_input_control(
        index,
        LinkCardFormField.DESTINATION,
        spec.label,
        link_card_form_destination(card, schema),
        input_type=spec.input_type,
        extra_input_attributes=input_attributes,
        extra_control_attributes=control_attributes,
    )


def _link_card_icon_control(card: LinkCard, index: int) -> HtmlNode:
    """Render an icon picker trigger backed by the submitted icon-path field."""

    attributes = _link_card_control_attributes(index, LinkCardFormField.ICON)
    attributes.update({"type": "hidden", "value": card.icon})
    return Div(
        Span("Icon path", cls="link-card-control__label"),
        Input(**attributes),
        Button(
            card.icon,
            type="button",
            aria_has_popup="dialog",
            aria_label=f"Choose icon for {card.title}. Current icon: {card.icon}",
            data_icon_picker_trigger="",
            data_icon_picker_card_title=card.title,
            cls="link-card-control__input link-card-icon-picker__trigger",
        ),
        cls="link-card-control",
    )


def _link_card_colour_pair(
    card: LinkCard,
    index: int,
    pair: LinkCardColourControlPair,
    colors: ThemeColors,
) -> HtmlNode:
    """Render the static and hover pickers for one LinkCard presentation area."""

    return Div(
        Div(
            Span(pair.label, cls="link-card-control__label"),
            cls="link-card-colour-pair__labels",
        ),
        Div(
            *(
                _link_card_colour_picker(card, index, control, colors)
                for control in pair.controls
            ),
            cls="link-card-colour-pair__controls",
        ),
        cls="link-card-control link-card-colour-pair",
    )


def _link_card_colour_picker(
    card: LinkCard,
    index: int,
    control: LinkCardColourControl,
    colors: ThemeColors,
) -> HtmlNode:
    """Render one optional per-card colour override with an Auto toggle."""

    override = link_card_colour_override(card, control.field)
    value = theme_color(colors, control.fallback_token).value
    if override is not None:
        value = override

    colour_attributes = _link_card_control_attributes(index, control.field)
    colour_attributes.update(
        {
            "type": "color",
            "value": value,
            "aria_label": f"Set {control.label.lower()} colour for {card.title}",
            "data_link_card_colour_fallback": control.fallback_token.value,
            "cls": "link-card-colour-control__input",
        }
    )
    auto_attributes = _link_card_control_attributes(index, control.auto_field)
    auto_attributes.update(
        {
            "type": "checkbox",
            "value": "true",
            "aria_label": f"Use automatic {control.label.lower()} colour",
            "data_link_card_colour_auto": "",
            "cls": "link-card-colour-control__auto-input",
        }
    )
    if override is None:
        auto_attributes["checked"] = ""
    return Div(
        Input(**colour_attributes),
        Label(
            Input(**auto_attributes),
            Span("Auto", cls="link-card-colour-control__auto-label"),
            cls="link-card-colour-control__auto",
        ),
        data_link_card_colour_control="",
        cls="link-card-colour-control__controls",
    )


def _link_card_textarea_control(
    index: int,
    field: LinkCardFormField,
    label: str,
    value: str,
) -> HtmlNode:
    """Render one labelled multi-line LinkCard editor control."""

    attributes = _link_card_control_attributes(index, field)
    attributes.update(
        {
            "rows": "2",
            "cls": "link-card-control__input link-card-control__textarea",
        }
    )
    return Label(
        Span(label, cls="link-card-control__label"),
        Textarea(value, **attributes),
        cls="link-card-control",
    )


def _link_card_select_control[OptionValue: StrEnum](
    index: int,
    field: LinkCardFormField,
    label: str,
    options: type[OptionValue],
    selected: OptionValue,
) -> HtmlNode:
    """Render one enum-backed LinkCard editor select control."""

    attributes = _link_card_control_attributes(index, field)
    attributes["cls"] = "link-card-control__input"
    return Label(
        Span(label, cls="link-card-control__label"),
        Select(
            *(_link_card_select_option(option, selected) for option in options),
            **attributes,
        ),
        cls="link-card-control",
    )


def _link_card_select_option[OptionValue: StrEnum](
    option: OptionValue,
    selected: OptionValue,
) -> HtmlNode:
    """Build one selected or unselected enum option."""

    attributes = {"value": option.value}
    if option is selected:
        attributes["selected"] = ""
    label = (
        LINK_CARD_DESTINATION_SPECS[option].schema_label
        if isinstance(option, CardKind)
        else option.value.replace("_", " ").title()
    )
    return Option(label, **attributes)


def _link_card_toggle_control(
    index: int,
    field: LinkCardFormField,
    label: str,
    checked: bool,
) -> HtmlNode:
    """Render one boolean LinkCard editor control."""

    attributes = _link_card_control_attributes(index, field)
    attributes.update(
        {
            "type": "checkbox",
            "value": "true",
            "cls": "link-card-toggle__input",
        }
    )
    if checked:
        attributes["checked"] = ""
    return Label(
        Input(**attributes),
        Span(label, cls="link-card-toggle__label"),
        cls="link-card-toggle",
    )


def _link_card_control_attributes(
    index: int,
    field: LinkCardFormField,
) -> dict[str, str]:
    """Return shared HTML attributes for one draft editor control."""

    attributes = {
        "name": link_card_form_name(index, field),
        "data_link_card_field": field.value,
    }
    if field is LinkCardFormField.SCHEMA:
        attributes["data_link_card_schema"] = ""
    return attributes


def _site_footer(current_page: SiteRoute | None = None) -> HtmlNode:
    """Render the shared footer and indicate the active page."""

    return Footer(
        Nav(
            Ul(
                *(
                    _site_navigation_link(page, label, current_page)
                    for page, label in _SITE_NAVIGATION
                ),
                cls="site-nav__list",
            ),
            aria_label="Site navigation",
            cls="site-nav",
        ),
        P("Critical Thinking is a Virtue", cls="signature"),
        cls="site-footer",
    )


def _site_navigation_link(
    page: SiteRoute,
    label: str,
    current_page: SiteRoute | None,
) -> HtmlNode:
    """Build one footer navigation link with its current-page state."""

    attributes = {"href": page.value, "cls": "site-nav__link"}
    if page is current_page:
        attributes["aria_current"] = "page"
    return Li(A(label, **attributes))
