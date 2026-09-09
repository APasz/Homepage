"""Field renderers for the LinkCard configuration editor."""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Literal

from apasz_hub.data import (
    LINK_CARD_DESTINATION_SPECS,
    CardKind,
    LinkCard,
    LinkCardColourControl,
    LinkCardColourControlPair,
    LinkCardFormField,
    LinkCardInputType,
    link_card_colour_override,
    link_card_form_destination,
    link_card_form_name,
)
from apasz_hub.framework import (
    Button,
    Div,
    HtmlNode,
    Input,
    Label,
    Option,
    Select,
    Span,
    Textarea,
)
from apasz_hub.theme import ThemeColors, theme_color

type EditorInputType = LinkCardInputType | Literal["number"]


def input_control(
    index: int,
    field: LinkCardFormField,
    label: str,
    value: str,
    *,
    input_type: EditorInputType = "text",
    minimum: int | None = None,
    extra_input_attributes: Mapping[str, str] | None = None,
    extra_control_attributes: Mapping[str, str] | None = None,
) -> HtmlNode:
    """Render one labelled single-line LinkCard editor control."""

    attributes = _field_attributes(index, field)
    attributes.update(
        {
            "type": input_type,
            "value": value,
            "cls": "link-card-control__input",
        }
    )
    if minimum is not None:
        attributes["min"] = str(minimum)
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


def destination_control(card: LinkCard, index: int, schema: CardKind) -> HtmlNode:
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
    return input_control(
        index,
        LinkCardFormField.DESTINATION,
        spec.label,
        link_card_form_destination(card, schema),
        input_type=spec.input_type,
        extra_input_attributes=input_attributes,
        extra_control_attributes=control_attributes,
    )


def icon_control(card: LinkCard, index: int) -> HtmlNode:
    """Render an icon picker trigger backed by the submitted icon-path field."""

    attributes = _field_attributes(index, LinkCardFormField.ICON)
    attributes.update(type="hidden", value=card.icon)
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


def colour_pair(
    card: LinkCard,
    index: int,
    pair: LinkCardColourControlPair,
    colors: ThemeColors,
) -> HtmlNode:
    """Render static and hover pickers for one LinkCard presentation area."""

    return Div(
        Div(
            Span(pair.label, cls="link-card-control__label"),
            cls="link-card-colour-pair__labels",
        ),
        Div(
            *(
                _colour_picker(card, index, control, colors)
                for control in pair.controls
            ),
            cls="link-card-colour-pair__controls",
        ),
        cls="link-card-control link-card-colour-pair",
    )


def textarea_control(
    index: int,
    field: LinkCardFormField,
    label: str,
    value: str,
) -> HtmlNode:
    """Render one labelled multi-line LinkCard editor control."""

    attributes = _field_attributes(index, field)
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


def select_control[OptionValue: StrEnum](
    index: int,
    field: LinkCardFormField,
    label: str,
    options: type[OptionValue],
    selected: OptionValue,
) -> HtmlNode:
    """Render one enum-backed LinkCard editor select control."""

    attributes = _field_attributes(index, field)
    attributes["cls"] = "link-card-control__input"
    return Label(
        Span(label, cls="link-card-control__label"),
        Select(
            *(_select_option(option, selected) for option in options),
            **attributes,
        ),
        cls="link-card-control",
    )


def toggle_control(
    index: int,
    field: LinkCardFormField,
    label: str,
    checked: bool,
) -> HtmlNode:
    """Render one boolean LinkCard editor control."""

    attributes = _field_attributes(index, field)
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


def _colour_picker(
    card: LinkCard,
    index: int,
    control: LinkCardColourControl,
    colors: ThemeColors,
) -> HtmlNode:
    """Render one optional per-card colour override with an Auto toggle."""

    override = link_card_colour_override(card, control.field)
    value = (
        theme_color(colors, control.fallback_token).value
        if override is None
        else override
    )
    colour_attributes = _field_attributes(index, control.field)
    colour_attributes.update(
        {
            "type": "color",
            "value": value,
            "aria_label": f"Set {control.label.lower()} colour for {card.title}",
            "data_link_card_colour_fallback": control.fallback_token.value,
            "cls": "link-card-colour-control__input",
        }
    )
    auto_attributes = _field_attributes(index, control.auto_field)
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


def _select_option[OptionValue: StrEnum](
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


def _field_attributes(index: int, field: LinkCardFormField) -> dict[str, str]:
    """Return shared HTML attributes for one draft editor control."""

    attributes = {
        "name": link_card_form_name(index, field),
        "data_link_card_field": field.value,
    }
    if field is LinkCardFormField.SCHEMA:
        attributes["data_link_card_schema"] = ""
    return attributes
