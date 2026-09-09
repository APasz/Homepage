"""The LinkCard configuration editor."""

from __future__ import annotations

from apasz_hub.components import ButtonStyle, button_class
from apasz_hub.data import (
    LINK_CARD_COLOUR_CONTROL_PAIRS,
    LINK_CARD_DELETE_INDEX_FORM_NAME,
    CardKind,
    CardTier,
    IconAsset,
    LinkCard,
    LinkCardFormField,
)
from apasz_hub.framework import (
    H2,
    Button,
    Details,
    Dialog,
    Div,
    Form,
    HtmlNode,
    Img,
    P,
    Section,
    Span,
    Summary,
)
from apasz_hub.routes.paths import SiteRoute
from apasz_hub.theme import ThemeColors

from .configuration_controls import csrf_token_input
from .link_card_controls import (
    colour_pair,
    destination_control,
    icon_control,
    input_control,
    select_control,
    textarea_control,
    toggle_control,
)


def link_card_manager(
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

    return Section(
        Div(
            H2("Link cards", cls="link-card-manager__title"),
            cls="link-card-manager__header",
        ),
        Form(
            csrf_token_input(csrf_token),
            Div(
                *(
                    _card_editor(card, index, colors)
                    for index, card in enumerate(cards)
                ),
                cls="link-card-manager__list",
            ),
            Div(
                P(
                    _status(saved, dirty),
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


def _card_editor(card: LinkCard, index: int, colors: ThemeColors) -> HtmlNode:
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
        _control_panel(card, index, colors),
        data_link_card_index=str(index),
        cls="link-card-manager__card",
    )


def _control_panel(card: LinkCard, index: int, colors: ThemeColors) -> HtmlNode:
    """Render schema-aware editable fields for one LinkCard draft entry."""

    return Div(
        select_control(
            index,
            LinkCardFormField.SCHEMA,
            "Schema",
            CardKind,
            card.schema,
        ),
        *(destination_control(card, index, schema) for schema in CardKind),
        input_control(index, LinkCardFormField.TITLE, "Title", card.title),
        select_control(
            index,
            LinkCardFormField.TIER,
            "Tier",
            CardTier,
            card.tier,
        ),
        icon_control(card, index),
        input_control(
            index,
            LinkCardFormField.ICON_SCALE,
            "Icon scale (%)",
            str(card.icon_scale),
            input_type="number",
            minimum=1,
        ),
        *(
            colour_pair(card, index, pair, colors)
            for pair in LINK_CARD_COLOUR_CONTROL_PAIRS
        ),
        input_control(
            index,
            LinkCardFormField.COPY_TEXT,
            "Copy value",
            card.copy_text or "",
        ),
        textarea_control(
            index,
            LinkCardFormField.DESCRIPTION,
            "Description",
            card.description or "",
        ),
        textarea_control(
            index,
            LinkCardFormField.METADATA,
            "Metadata",
            card.metadata or "",
        ),
        Div(
            toggle_control(
                index,
                LinkCardFormField.OPENS_IN_NEW_TAB,
                "Open in a new tab",
                card.opens_in_new_tab,
            ),
            toggle_control(
                index,
                LinkCardFormField.COPY_TO_CLIPBOARD,
                "Copy to clipboard",
                card.copy_to_clipboard,
            ),
            cls="link-card-toggle-pair",
        ),
        cls="link-card-panel",
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


def _status(saved: bool, dirty: bool) -> str:
    """Return the editor status consistent with its draft lifecycle."""

    if saved:
        return "Link cards saved"
    if dirty:
        return "Draft changes"
    return "Linkerate"
