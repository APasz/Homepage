"""Regression checks for the profile-media build helper."""

from __future__ import annotations

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from tools import build_profile_media
from tools.build_profile_media import create_temporary_path


class ProfileMediaTests(TestCase):
    """Ensure profile-media builds are reliable and preserve image fidelity."""

    def test_webp_builds_preserve_the_resized_frames(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.webp"
            source.touch()
            media_directory = root / "media"
            animated_output = media_directory / "animated.webp"
            still_output = media_directory / "still.webp"
            favicon_output = media_directory / "favicon.png"

            with (
                redirect_stdout(StringIO()),
                patch.object(build_profile_media, "PROFILE_SOURCE", source),
                patch.object(
                    build_profile_media, "PUBLIC_MEDIA_DIRECTORY", media_directory
                ),
                patch.object(build_profile_media, "PROFILE_OUTPUT", animated_output),
                patch.object(
                    build_profile_media,
                    "PROFILE_REDUCED_MOTION_OUTPUT",
                    still_output,
                ),
                patch.object(build_profile_media, "FAVICON_OUTPUT", favicon_output),
                patch.object(
                    build_profile_media.shutil, "which", return_value="magick"
                ),
                patch.object(build_profile_media, "_run_magick") as run_magick,
                patch.object(build_profile_media, "_validate_output"),
            ):
                self.assertEqual(build_profile_media.main(), 0)

            animated_arguments = run_magick.call_args_list[0].args
            self.assertEqual(
                animated_arguments[:-1],
                (
                    "magick",
                    str(source),
                    "-coalesce",
                    "-resize",
                    f"{build_profile_media.PROFILE_SIZE}x{build_profile_media.PROFILE_SIZE}",
                    "-strip",
                    *build_profile_media.LOSSLESS_WEBP_OPTIONS,
                ),
            )
            self.assertEqual(Path(animated_arguments[-1]).parent, media_directory)
            self.assertEqual(Path(animated_arguments[-1]).suffix, ".webp")

            still_arguments = run_magick.call_args_list[1].args
            self.assertEqual(
                still_arguments[:-1],
                (
                    "magick",
                    f"{source}[0]",
                    "-resize",
                    f"{build_profile_media.PROFILE_SIZE}x{build_profile_media.PROFILE_SIZE}",
                    "-strip",
                    *build_profile_media.LOSSLESS_WEBP_OPTIONS,
                ),
            )
            self.assertEqual(Path(still_arguments[-1]).parent, media_directory)
            self.assertEqual(Path(still_arguments[-1]).suffix, ".webp")

    def test_temporary_paths_are_unique_and_keep_the_output_suffix(self) -> None:
        with TemporaryDirectory() as directory:
            output = Path(directory) / "favicon.png"

            first_temporary = create_temporary_path(output)
            second_temporary = create_temporary_path(output)

            self.assertNotEqual(first_temporary, second_temporary)
            self.assertEqual(first_temporary.parent, output.parent)
            self.assertEqual(second_temporary.parent, output.parent)
            self.assertEqual(first_temporary.suffix, output.suffix)
            self.assertEqual(second_temporary.suffix, output.suffix)
            self.assertTrue(first_temporary.is_file())
            self.assertTrue(second_temporary.is_file())

    def test_failed_second_temporary_path_cleans_up_the_first(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.webp"
            source.touch()
            media_directory = root / "media"
            profile_output = media_directory / "profile.webp"
            reduced_motion_output = media_directory / "profile-still.webp"
            favicon_output = media_directory / "favicon.png"
            profile_temporary = media_directory / ".profile-intermediate.webp"
            error_output = StringIO()

            with (
                redirect_stderr(error_output),
                patch.object(build_profile_media, "PROFILE_SOURCE", source),
                patch.object(
                    build_profile_media, "PUBLIC_MEDIA_DIRECTORY", media_directory
                ),
                patch.object(build_profile_media, "PROFILE_OUTPUT", profile_output),
                patch.object(
                    build_profile_media,
                    "PROFILE_REDUCED_MOTION_OUTPUT",
                    reduced_motion_output,
                ),
                patch.object(build_profile_media, "FAVICON_OUTPUT", favicon_output),
                patch.object(
                    build_profile_media.shutil, "which", return_value="magick"
                ),
                patch.object(
                    build_profile_media,
                    "create_temporary_path",
                    side_effect=(profile_temporary, OSError("disk full")),
                ),
            ):
                profile_temporary.parent.mkdir()
                profile_temporary.touch()

                self.assertEqual(build_profile_media.main(), 1)

            self.assertFalse(profile_temporary.exists())
            self.assertIn(
                "Unable to build profile media: disk full", error_output.getvalue()
            )

    def test_successful_build_reports_outputs_outside_the_project_root(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "source.webp"
            source.touch()
            media_directory = root / "media"
            profile_output = media_directory / "profile.webp"
            reduced_motion_output = media_directory / "profile-still.webp"
            favicon_output = media_directory / "favicon.png"
            output = StringIO()

            with (
                redirect_stdout(output),
                patch.object(build_profile_media, "PROFILE_SOURCE", source),
                patch.object(
                    build_profile_media, "PUBLIC_MEDIA_DIRECTORY", media_directory
                ),
                patch.object(build_profile_media, "PROFILE_OUTPUT", profile_output),
                patch.object(
                    build_profile_media,
                    "PROFILE_REDUCED_MOTION_OUTPUT",
                    reduced_motion_output,
                ),
                patch.object(build_profile_media, "FAVICON_OUTPUT", favicon_output),
                patch.object(
                    build_profile_media.shutil, "which", return_value="magick"
                ),
                patch.object(build_profile_media, "_build_animated_profile"),
                patch.object(
                    build_profile_media,
                    "_build_reduced_motion_profile",
                ) as build_reduced_motion_profile,
                patch.object(build_profile_media, "_build_favicon"),
                patch.object(build_profile_media, "_validate_output"),
            ):
                self.assertEqual(build_profile_media.main(), 0)

            self.assertIn(f"Built {profile_output}", output.getvalue())
            self.assertIn(f"Built {reduced_motion_output}", output.getvalue())
            self.assertIn(f"Built {favicon_output}", output.getvalue())
            build_reduced_motion_profile.assert_called_once()
