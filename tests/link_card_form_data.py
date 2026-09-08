"""Shared builders for complete LinkCard editor form submissions."""

from __future__ import annotations

from apasz_hub.data import (
    LINK_CARD_COLOUR_CONTROLS,
    LinkCard,
    LinkCardFormField,
    link_card_colour_override,
    link_card_form_destination,
    link_card_form_name,
)


def link_card_form_values(cards: tuple[LinkCard, ...]) -> dict[str, str]:
    """Return all successful controls for an existing LinkCard draft."""

    values: dict[str, str] = {}
    for index, card in enumerate(cards):
        values.update(
            {
                link_card_form_name(index, LinkCardFormField.TITLE): card.title,
                link_card_form_name(
                    index, LinkCardFormField.DESTINATION
                ): link_card_form_destination(card, card.schema),
                link_card_form_name(index, LinkCardFormField.TIER): card.tier.value,
                link_card_form_name(index, LinkCardFormField.ICON): card.icon,
                link_card_form_name(
                    index, LinkCardFormField.DESCRIPTION
                ): card.description or "",
                link_card_form_name(index, LinkCardFormField.ICON_SCALE): str(
                    card.icon_scale
                ),
                link_card_form_name(index, LinkCardFormField.METADATA): card.metadata
                or "",
                link_card_form_name(index, LinkCardFormField.SCHEMA): card.schema.value,
                link_card_form_name(index, LinkCardFormField.COPY_TEXT): card.copy_text
                or "",
            }
        )
        if card.opens_in_new_tab:
            values[link_card_form_name(index, LinkCardFormField.OPENS_IN_NEW_TAB)] = (
                "true"
            )
        if card.copy_to_clipboard:
            values[link_card_form_name(index, LinkCardFormField.COPY_TO_CLIPBOARD)] = (
                "true"
            )
        for control in LINK_CARD_COLOUR_CONTROLS:
            override = link_card_colour_override(card, control.field)
            if override is None:
                values[link_card_form_name(index, control.auto_field)] = "true"
            else:
                values[link_card_form_name(index, control.field)] = override
    return values
