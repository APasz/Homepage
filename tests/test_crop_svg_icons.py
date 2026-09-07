"""Failure handling checks for the SVG crop helper."""

from __future__ import annotations

from contextlib import redirect_stderr
from io import StringIO
from pathlib import Path
from subprocess import CompletedProcess
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tools import crop_svg_icons


class CropSvgIconsTests(TestCase):
    """Ensure asset-cropping failures preserve the source icon."""

    def test_rejects_icons_outside_the_asset_directory(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            icon_directory = root / "icons"
            icon_directory.mkdir()
            outside_icon = root / "outside.svg"
            outside_icon.write_text("<svg />", encoding="utf-8")
            error_output = StringIO()

            with (
                patch.object(crop_svg_icons, "ICON_DIRECTORY", icon_directory),
                patch.object(crop_svg_icons.shutil, "which", return_value="inkscape"),
                redirect_stderr(error_output),
            ):
                self.assertEqual(crop_svg_icons.main((str(outside_icon),)), 1)

            self.assertIn("inside", error_output.getvalue())

    def test_success_without_an_output_file_preserves_the_source_icon(self) -> None:
        with TemporaryDirectory() as directory:
            icon_path = Path(directory) / "icon.svg"
            original_contents = "<svg><path /></svg>"
            icon_path.write_text(original_contents, encoding="utf-8")
            error_output = StringIO()

            def successful_run_without_output(
                arguments: tuple[str, ...],
                **_options: object,
            ) -> CompletedProcess[str]:
                output_argument = next(
                    argument
                    for argument in arguments
                    if argument.startswith("--export-filename=")
                )
                Path(output_argument.removeprefix("--export-filename=")).unlink()
                return CompletedProcess(arguments, 0, "", "")

            with (
                patch.object(crop_svg_icons, "ICON_DIRECTORY", icon_path.parent),
                patch.object(crop_svg_icons.shutil, "which", return_value="inkscape"),
                patch.object(
                    crop_svg_icons.subprocess,
                    "run",
                    side_effect=successful_run_without_output,
                ),
                redirect_stderr(error_output),
            ):
                self.assertEqual(crop_svg_icons.main((str(icon_path),)), 1)

            self.assertEqual(icon_path.read_text(encoding="utf-8"), original_contents)
            self.assertEqual(tuple(icon_path.parent.glob(".icon-crop-*.svg")), ())
            self.assertIn("did not produce a usable SVG", error_output.getvalue())

    def test_filesystem_failure_preserves_the_source_icon(self) -> None:
        with TemporaryDirectory() as directory:
            icon_path = Path(directory) / "icon.svg"
            original_contents = "<svg><path /></svg>"
            icon_path.write_text(original_contents, encoding="utf-8")
            error_output = StringIO()

            def successful_run_with_output(
                arguments: tuple[str, ...],
                **_options: object,
            ) -> CompletedProcess[str]:
                output_argument = next(
                    argument
                    for argument in arguments
                    if argument.startswith("--export-filename=")
                )
                Path(output_argument.removeprefix("--export-filename=")).write_text(
                    "<svg><path /></svg>",
                    encoding="utf-8",
                )
                return CompletedProcess(arguments, 0, "", "")

            with (
                patch.object(crop_svg_icons, "ICON_DIRECTORY", icon_path.parent),
                patch.object(crop_svg_icons.shutil, "which", return_value="inkscape"),
                patch.object(
                    crop_svg_icons.subprocess,
                    "run",
                    side_effect=successful_run_with_output,
                ),
                patch.object(
                    crop_svg_icons.os, "replace", side_effect=OSError("disk full")
                ),
                redirect_stderr(error_output),
            ):
                self.assertEqual(crop_svg_icons.main((str(icon_path),)), 1)

            self.assertEqual(icon_path.read_text(encoding="utf-8"), original_contents)
            self.assertEqual(tuple(icon_path.parent.glob(".icon-crop-*.svg")), ())
            self.assertIn(
                "Unable to crop SVG icons: disk full", error_output.getvalue()
            )
