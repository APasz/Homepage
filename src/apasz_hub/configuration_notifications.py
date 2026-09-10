"""Friendly, compact descriptions of published configuration changes."""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, fields
from difflib import SequenceMatcher
from typing import Final

from apasz_hub.data import CardKind, CardTier, LinkCard, SiteMetadata
from apasz_hub.open_graph import (
    OPEN_GRAPH_FIELD_DEFINITIONS,
    open_graph_field_value,
)
from apasz_hub.theme import ThemeColors

MAXIMUM_CHANGE_LINES: Final = 8
MAXIMUM_CARD_NAMES_PER_LINE: Final = 3
MAXIMUM_DISPLAY_VALUE_LENGTH: Final = 120

type LinkCardValue = str | int | bool | CardKind | CardTier | None


@dataclass(frozen=True, slots=True)
class _LinkCardField:
    """One user-facing LinkCard field that can appear in a change summary."""

    name: str
    label: str
    value: Callable[[LinkCard], LinkCardValue]


_LINK_CARD_FIELDS: Final[tuple[_LinkCardField, ...]] = (
    _LinkCardField("title", "title", lambda card: card.title),
    _LinkCardField("href", "destination", lambda card: card.href),
    _LinkCardField("tier", "tier", lambda card: card.tier),
    _LinkCardField("icon", "icon", lambda card: card.icon),
    _LinkCardField("description", "description", lambda card: card.description),
    _LinkCardField("border_hover", "hover border", lambda card: card.border_hover),
    _LinkCardField("icon_scale", "icon size", lambda card: card.icon_scale),
    _LinkCardField("border_static", "static border", lambda card: card.border_static),
    _LinkCardField("icon_static", "static icon", lambda card: card.icon_static),
    _LinkCardField("icon_hover", "hover icon", lambda card: card.icon_hover),
    _LinkCardField("metadata", "metadata", lambda card: card.metadata),
    _LinkCardField("schema", "type", lambda card: card.schema),
    _LinkCardField(
        "opens_in_new_tab",
        "open-in-new-tab setting",
        lambda card: card.opens_in_new_tab,
    ),
    _LinkCardField(
        "copy_to_clipboard",
        "copy-to-clipboard setting",
        lambda card: card.copy_to_clipboard,
    ),
    _LinkCardField("copy_text", "copy text", lambda card: card.copy_text),
)

if {field.name for field in _LINK_CARD_FIELDS} != {
    field.name for field in fields(LinkCard)
}:
    raise RuntimeError("Link-card notification fields must cover every LinkCard field.")


def theme_colors_notification_detail(
    previous: ThemeColors,
    current: ThemeColors,
) -> str:
    """Describe the live palette values that changed in one save."""

    changes = tuple(
        f"{current_color.label}: {previous_color.value} -> {current_color.value}"
        for previous_color, current_color in zip(previous, current, strict=True)
        if previous_color.value != current_color.value
    )
    return _configuration_detail("Your site colours are live.", changes)


def open_graph_notification_detail(
    previous: SiteMetadata,
    current: SiteMetadata,
) -> str:
    """Describe the public sharing values that changed in one save."""

    changes: list[str] = []
    for definition in OPEN_GRAPH_FIELD_DEFINITIONS:
        previous_value = open_graph_field_value(previous, definition.field)
        current_value = open_graph_field_value(current, definition.field)
        if previous_value != current_value:
            changes.append(
                f"{definition.label}: {_display_value(previous_value)} "
                f"-> {_display_value(current_value)}"
            )
    return _configuration_detail("Your sharing info is live.", tuple(changes))


def link_cards_notification_detail(
    previous: tuple[LinkCard, ...],
    current: tuple[LinkCard, ...],
) -> str:
    """Describe published LinkCard additions, removals, edits, and reordering."""

    if previous == current:
        return _configuration_detail("Your link cards are live.", ())
    if Counter(previous) == Counter(current):
        return _configuration_detail(
            "Your link cards are live.", ("Card order changed.",)
        )

    changes: list[str] = []
    matcher = SequenceMatcher(a=previous, b=current, autojunk=False)
    for (
        tag,
        previous_start,
        previous_end,
        current_start,
        current_end,
    ) in matcher.get_opcodes():
        if tag == "equal":
            continue
        previous_cards = previous[previous_start:previous_end]
        current_cards = current[current_start:current_end]
        if tag == "replace" and len(previous_cards) == len(current_cards):
            changes.extend(
                _updated_card_detail(before, after)
                for before, after in zip(previous_cards, current_cards, strict=True)
            )
            continue
        removed = _card_group_detail("Removed", previous_cards)
        if removed is not None:
            changes.append(removed)
        added = _card_group_detail("Added", current_cards)
        if added is not None:
            changes.append(added)

    return _configuration_detail("Your link cards are live.", tuple(changes))


def _configuration_detail(introduction: str, changes: tuple[str, ...]) -> str:
    """Render a friendly message body for a published configuration snapshot."""

    if not changes:
        return f"{introduction}\n\nNothing actually changed — it was just saved again."
    return "\n".join(
        (
            introduction,
            "",
            "What changed:",
            *(f"- {change}" for change in _limited_changes(changes)),
        )
    )


def _limited_changes(changes: tuple[str, ...]) -> tuple[str, ...]:
    """Keep one large save from producing an unhelpfully long email."""

    if len(changes) <= MAXIMUM_CHANGE_LINES:
        return changes
    remaining_count = len(changes) - MAXIMUM_CHANGE_LINES
    return (*changes[:MAXIMUM_CHANGE_LINES], f"…and {remaining_count} more.")


def _display_value(value: str) -> str:
    """Quote a short, single-line public configuration value for an email."""

    if not value:
        return "not set"
    return f'"{_short_text(value)}"'


def _updated_card_detail(previous: LinkCard, current: LinkCard) -> str:
    """Describe one edited LinkCard without repeating all of its public data."""

    changed_labels = tuple(
        field.label
        for field in _LINK_CARD_FIELDS
        if field.value(previous) != field.value(current) and field.name != "title"
    )
    if previous.title != current.title:
        rename = f"Renamed {_card_name(previous)} -> {_card_name(current)}"
        if not changed_labels:
            return f"{rename}."
        return f"{rename}; also updated {_natural_list(changed_labels)}."
    if not changed_labels:
        raise RuntimeError("Changed LinkCard has no changed notification fields.")
    return f"Updated {_card_name(current)}: {_natural_list(changed_labels)}."


def _card_group_detail(action: str, cards: tuple[LinkCard, ...]) -> str | None:
    """Describe a contiguous insertion or removal in a LinkCard list."""

    if not cards:
        return None
    names = tuple(_card_name(card) for card in cards[:MAXIMUM_CARD_NAMES_PER_LINE])
    remaining_count = len(cards) - len(names)
    description = _natural_list(names)
    if remaining_count:
        description = f"{description}, and {remaining_count} more"
    return f"{action}: {description}."


def _card_name(card: LinkCard) -> str:
    """Return a compact, readable reference to a public LinkCard."""

    return f'"{_short_text(card.title)}"'


def _short_text(value: str) -> str:
    """Collapse formatting and cap arbitrary user text for a plain-text email."""

    printable_value = "".join(
        character if character.isprintable() else " " for character in value
    )
    normalised = " ".join(printable_value.split())
    if len(normalised) <= MAXIMUM_DISPLAY_VALUE_LENGTH:
        return normalised
    return f"{normalised[: MAXIMUM_DISPLAY_VALUE_LENGTH - 1].rstrip()}…"


def _natural_list(values: tuple[str, ...]) -> str:
    """Join a non-empty tuple using ordinary English punctuation."""

    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"
