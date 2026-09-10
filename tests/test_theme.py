"""Tests for the persisted shared colour palette."""

from __future__ import annotations

import os
from json import dumps
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from apasz_hub.settings import SettingsValidationError
from apasz_hub.theme import (
    DEFAULT_THEME_COLORS_PATH,
    THEME_COLORS_PATH_ENV,
    ThemeColorDataError,
    ThemeColorStore,
    ThemeColorToken,
    load_theme_colors,
    save_theme_colors,
    theme_color,
    theme_stylesheet,
)


def _palette_values() -> dict[str, object]:
    """Return a complete copy of the checked-in palette fields."""

    return {color.token.value: color.value for color in load_theme_colors()}


def _contrast_ratio(first: str, second: str) -> float:
    """Return the WCAG contrast ratio between two validated hexadecimal colours."""

    first_luminance = _relative_luminance(first)
    second_luminance = _relative_luminance(second)
    lighter, darker = sorted((first_luminance, second_luminance), reverse=True)
    return (lighter + 0.05) / (darker + 0.05)


def _relative_luminance(value: str) -> float:
    """Convert a six-digit sRGB hexadecimal colour into relative luminance."""

    red, green, blue = (int(value[index : index + 2], 16) for index in (1, 3, 5))
    return (
        0.2126 * _linearised_srgb_channel(red)
        + 0.7152 * _linearised_srgb_channel(green)
        + 0.0722 * _linearised_srgb_channel(blue)
    )


def _linearised_srgb_channel(channel: int) -> float:
    """Return one 8-bit sRGB channel in linear-light form."""

    srgb = channel / 255
    if srgb <= 0.04045:
        return srgb / 12.92
    return ((srgb + 0.055) / 1.055) ** 2.4


class ThemeColorDataTests(TestCase):
    """Keep editable palette data strict, persistent, and stylesheet-ready."""

    def test_save_replaces_a_complete_palette_and_stylesheet_uses_it(self) -> None:
        values = _palette_values()
        values[ThemeColorToken.SHADOW.value] = "#123456"

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "theme_colors.json"
            colors = save_theme_colors(values, path)
            saved_document = path.read_text(encoding="utf-8")

        self.assertEqual(
            saved_document,
            dumps(values, indent=4) + "\n",
        )
        self.assertEqual(
            theme_color(colors, ThemeColorToken.SHADOW).value,
            "#123456",
        )
        self.assertIn(
            "--shadow: rgb(18 52 86 / var(--shadow-opacity));",
            theme_stylesheet(colors),
        )

    def test_load_rejects_duplicate_theme_colour_fields(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "theme_colors.json"
            path.write_text(
                '{"canvas":"#000000","canvas":"#ffffff"}',
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                ThemeColorDataError,
                "Duplicate theme-colour field 'canvas'",
            ):
                load_theme_colors(path)

    def test_load_rejects_incomplete_or_invalid_palettes(self) -> None:
        cases = (
            ("missing", {ThemeColorToken.CANVAS.value: "#000000"}),
            ("unknown", {**_palette_values(), "brand": "#123456"}),
            (
                "invalid value",
                {**_palette_values(), ThemeColorToken.ACCENT.value: "purple"},
            ),
        )

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "theme_colors.json"
            for name, values in cases:
                with self.subTest(name=name):
                    path.write_text(dumps(values), encoding="utf-8")
                    with self.assertRaises(ThemeColorDataError):
                        load_theme_colors(path)

    def test_store_keeps_the_published_snapshot_when_json_changes_externally(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "theme_colors.json"
            path.write_text(
                DEFAULT_THEME_COLORS_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            store = ThemeColorStore(path)
            published_colors = store.load()

            external_values = {
                color.token.value: color.value for color in published_colors
            }
            external_values[ThemeColorToken.CANVAS.value] = "#123456"
            path.write_text(dumps(external_values), encoding="utf-8")
            self.assertEqual(store.published_colors(), published_colors)

            path.write_text("{not valid JSON", encoding="utf-8")

        self.assertEqual(store.published_colors(), published_colors)

    def test_store_save_persists_and_publishes_a_valid_palette(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "theme_colors.json"
            path.write_text(
                DEFAULT_THEME_COLORS_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            store = ThemeColorStore(path)
            store.load()
            values = {
                color.token.value: color.value for color in store.published_colors()
            }
            values[ThemeColorToken.CANVAS.value] = "#123456"

            saved_colors = store.save(values)
            persisted_colors = load_theme_colors(path)

        self.assertEqual(store.published_colors(), saved_colors)
        self.assertEqual(persisted_colors, saved_colors)

    def test_store_saves_to_the_path_loaded_at_startup(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            startup_path = directory / "startup_theme_colors.json"
            changed_path = directory / "changed_theme_colors.json"
            startup_values = _palette_values()
            changed_values = {
                **startup_values,
                ThemeColorToken.CANVAS.value: "#654321",
            }
            startup_path.write_text(dumps(startup_values), encoding="utf-8")
            changed_path.write_text(dumps(changed_values), encoding="utf-8")

            with patch.dict(
                os.environ,
                {THEME_COLORS_PATH_ENV: str(startup_path)},
            ):
                store = ThemeColorStore()
                store.load()
            saved_values = {
                color.token.value: color.value for color in store.published_colors()
            }
            saved_values[ThemeColorToken.CANVAS.value] = "#123456"

            with patch.dict(
                os.environ,
                {THEME_COLORS_PATH_ENV: str(changed_path)},
            ):
                store.save(saved_values)
            saved_startup_colors = load_theme_colors(startup_path)
            unchanged_changed_colors = load_theme_colors(changed_path)

        self.assertEqual(
            theme_color(saved_startup_colors, ThemeColorToken.CANVAS).value,
            "#123456",
        )
        self.assertEqual(
            theme_color(unchanged_changed_colors, ThemeColorToken.CANVAS).value,
            "#654321",
        )

    def test_empty_palette_path_override_fails_loudly(self) -> None:
        with (
            patch.dict(
                os.environ,
                {THEME_COLORS_PATH_ENV: "   "},
            ),
            self.assertRaisesRegex(
                SettingsValidationError,
                f"{THEME_COLORS_PATH_ENV}: must not be empty",
            ),
        ):
            load_theme_colors()

    def test_checked_in_palette_is_loadable(self) -> None:
        colors = load_theme_colors(DEFAULT_THEME_COLORS_PATH)

        self.assertEqual(
            tuple(color.token for color in colors),
            tuple(ThemeColorToken),
        )

    def test_checked_in_palette_has_sufficient_non_text_contrast(self) -> None:
        """Keep UI borders and accent insets discernible across dark surfaces."""

        colors = load_theme_colors(DEFAULT_THEME_COLORS_PATH)
        values = {color.token: color.value for color in colors}
        backgrounds = (
            ThemeColorToken.CANVAS,
            ThemeColorToken.SURFACE,
            ThemeColorToken.SURFACE_RAISED,
            ThemeColorToken.SURFACE_HOVER,
        )

        for boundary in (ThemeColorToken.BORDER, ThemeColorToken.ACCENT_MUTED):
            for background in backgrounds:
                with self.subTest(boundary=boundary, background=background):
                    self.assertGreaterEqual(
                        _contrast_ratio(values[boundary], values[background]),
                        3.0,
                    )
