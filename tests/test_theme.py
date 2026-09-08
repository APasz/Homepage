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
    ThemeColorToken,
    load_theme_colors,
    save_theme_colors,
    theme_color,
    theme_stylesheet,
)


def _palette_values() -> dict[str, object]:
    """Return a complete copy of the checked-in palette fields."""

    return {color.token.value: color.value for color in load_theme_colors()}


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
