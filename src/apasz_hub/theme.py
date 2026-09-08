"""The shared, persisted colour palette for the APasz hub."""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from json import dumps
from pathlib import Path
from re import compile
from typing import Final

from apasz_hub.json_data import (
    json_object_fields,
    load_json_document,
    write_json_document,
)


class ThemeColorToken(StrEnum):
    """Named colours used by the shared site interface."""

    CANVAS = "canvas"
    SURFACE = "surface"
    SURFACE_RAISED = "surface-raised"
    SURFACE_HOVER = "surface-hover"
    BORDER = "border"
    TEXT = "text"
    MUTED = "muted"
    SUBTLE = "subtle"
    ACCENT = "accent"
    ACCENT_MUTED = "accent-muted"
    METADATA = "metadata"
    SHADOW = "shadow"


_HEX_COLOUR = compile(r"#[0-9a-fA-F]{6}\Z")


def is_hex_colour(value: str) -> bool:
    """Whether a value is a six-digit hexadecimal CSS colour."""

    return _HEX_COLOUR.fullmatch(value) is not None


@dataclass(frozen=True, slots=True)
class ThemeColorDefinition:
    """Stable metadata for one persisted palette entry."""

    token: ThemeColorToken
    label: str


@dataclass(frozen=True, slots=True)
class ThemeColor:
    """One loaded colour and the CSS custom property it supplies."""

    token: ThemeColorToken
    label: str
    value: str

    def __post_init__(self) -> None:
        if not is_hex_colour(self.value):
            raise ValueError(
                f"Theme colour {self.token.value} must be a six-digit hex value."
            )

    @property
    def css_variable(self) -> str:
        """Return the CSS custom-property name assigned to this colour."""

        return f"--color-{self.token.value}"


class ThemeColorDataError(ValueError):
    """Raised when persisted theme-colour data cannot be loaded or saved."""


type ThemeColors = tuple[ThemeColor, ...]

THEME_STYLESHEET_URL: Final = "/theme.css"
THEME_STYLESHEET_CACHE_CONTROL: Final = "no-store"
DEFAULT_THEME_COLORS_PATH: Final = Path(__file__).with_name("theme_colors.json")
THEME_COLORS_PATH_ENV: Final = "APASZ_HUB_THEME_COLORS_PATH"
THEME_COLOR_DEFINITIONS: Final[tuple[ThemeColorDefinition, ...]] = (
    ThemeColorDefinition(ThemeColorToken.CANVAS, "Canvas"),
    ThemeColorDefinition(ThemeColorToken.SURFACE, "Surface"),
    ThemeColorDefinition(ThemeColorToken.SURFACE_RAISED, "Raised surface"),
    ThemeColorDefinition(ThemeColorToken.SURFACE_HOVER, "Hover surface"),
    ThemeColorDefinition(ThemeColorToken.BORDER, "Border"),
    ThemeColorDefinition(ThemeColorToken.TEXT, "Primary text"),
    ThemeColorDefinition(ThemeColorToken.MUTED, "Muted text"),
    ThemeColorDefinition(ThemeColorToken.SUBTLE, "Subtle text"),
    ThemeColorDefinition(ThemeColorToken.ACCENT, "Primary accent"),
    ThemeColorDefinition(ThemeColorToken.ACCENT_MUTED, "Muted accent"),
    ThemeColorDefinition(ThemeColorToken.METADATA, "Metadata"),
    ThemeColorDefinition(ThemeColorToken.SHADOW, "Shadow"),
)

if len(THEME_COLOR_DEFINITIONS) != len(ThemeColorToken) or {
    definition.token for definition in THEME_COLOR_DEFINITIONS
} != set(ThemeColorToken):
    raise RuntimeError("Every theme colour token must have exactly one definition.")


def load_theme_colors(path: Path | None = None) -> ThemeColors:
    """Load and validate the persisted shared palette."""

    data_path = _configured_theme_colors_path() if path is None else path
    raw_data = load_json_document(
        data_path,
        data_name="theme-colour data",
        duplicate_field_name="theme-colour field",
        error_type=ThemeColorDataError,
    )
    return _theme_colors_from_fields(
        json_object_fields(
            raw_data, "Theme-colour data", error_type=ThemeColorDataError
        )
    )


def save_theme_colors(
    values: Mapping[str, object],
    path: Path | None = None,
) -> ThemeColors:
    """Validate and atomically persist a complete shared palette."""

    colors = _theme_colors_from_fields(values)
    data_path = _configured_theme_colors_path() if path is None else path
    document = (
        dumps(
            {color.token.value: color.value for color in colors},
            indent=4,
        )
        + "\n"
    )
    write_json_document(
        data_path,
        document,
        data_name="theme-colour data",
        error_type=ThemeColorDataError,
    )
    return colors


def theme_color(colors: ThemeColors, token: ThemeColorToken) -> ThemeColor:
    """Return one loaded palette entry by its stable token."""

    for color in colors:
        if color.token is token:
            return color
    raise RuntimeError(f"Theme palette is missing {token.value}.")


def theme_stylesheet(colors: ThemeColors) -> str:
    """Build CSS custom properties from the loaded palette."""

    declarations = "\n".join(
        f"    {color.css_variable}: {color.value};" for color in colors
    )
    shadow = theme_color(colors, ThemeColorToken.SHADOW)
    return (
        f":root {{\n{declarations}\n"
        f"    --shadow: {_shadow_css_value(shadow.value)};\n"
        "}\n"
    )


def _shadow_css_value(value: str) -> str:
    """Convert a validated hex colour to the portable CSS shadow syntax."""

    red = int(value[1:3], 16)
    green = int(value[3:5], 16)
    blue = int(value[5:7], 16)
    return f"rgb({red} {green} {blue} / var(--shadow-opacity))"


def _configured_theme_colors_path() -> Path:
    """Return the packaged default or explicitly writable palette file path."""

    configured_path = os.environ.get(THEME_COLORS_PATH_ENV)
    if configured_path is None:
        return DEFAULT_THEME_COLORS_PATH
    configured_path = configured_path.strip()
    if not configured_path:
        raise ThemeColorDataError(f"{THEME_COLORS_PATH_ENV} must not be empty.")
    return Path(configured_path)


def _theme_colors_from_fields(values: Mapping[str, object]) -> ThemeColors:
    expected_names = {definition.token.value for definition in THEME_COLOR_DEFINITIONS}
    unknown_names = sorted(set(values) - expected_names)
    if unknown_names:
        raise ThemeColorDataError(
            f"Theme-colour data has unsupported field(s): {', '.join(unknown_names)}."
        )
    missing_names = [
        definition.token.value
        for definition in THEME_COLOR_DEFINITIONS
        if definition.token.value not in values
    ]
    if missing_names:
        raise ThemeColorDataError(
            f"Theme-colour data is missing required field(s): {', '.join(missing_names)}."
        )

    colors: list[ThemeColor] = []
    for definition in THEME_COLOR_DEFINITIONS:
        value = values[definition.token.value]
        if not isinstance(value, str) or not is_hex_colour(value):
            raise ThemeColorDataError(
                f"Theme-colour field {definition.token.value!r} must be a six-digit hex value."
            )
        colors.append(ThemeColor(definition.token, definition.label, value))
    return tuple(colors)
