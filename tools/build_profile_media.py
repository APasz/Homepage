"""Build public profile-media assets from the canonical animation."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from contextlib import ExitStack
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Final

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[1]
PROFILE_SOURCE: Final[Path] = PROJECT_ROOT / "assets" / "profile" / "pfp-anim.webp"
PUBLIC_MEDIA_DIRECTORY: Final[Path] = (
    PROJECT_ROOT / "src" / "apasz_hub" / "static" / "media"
)
PROFILE_OUTPUT: Final[Path] = PUBLIC_MEDIA_DIRECTORY / "pfp-anim.webp"
PROFILE_REDUCED_MOTION_OUTPUT: Final[Path] = PUBLIC_MEDIA_DIRECTORY / "pfp-still.webp"
FAVICON_OUTPUT: Final[Path] = PUBLIC_MEDIA_DIRECTORY / "favicon.png"
PROFILE_SIZE: Final[int] = 256
FAVICON_SIZE: Final[int] = 64
LOSSLESS_WEBP_OPTIONS: Final[tuple[str, ...]] = (
    "-define",
    "webp:lossless=true",
    "-define",
    "webp:exact=true",
)


def main() -> int:
    """Write animated, reduced-motion, and favicon assets via atomic replacements."""

    if not PROFILE_SOURCE.is_file():
        print(f"Missing profile source: {PROFILE_SOURCE}", file=sys.stderr)
        return 1

    magick: str | None = shutil.which("magick")
    if magick is None:
        print(
            "ImageMagick 7 ('magick') is required to build profile media.",
            file=sys.stderr,
        )
        return 1

    try:
        PUBLIC_MEDIA_DIRECTORY.mkdir(parents=True, exist_ok=True)
        with ExitStack() as temporary_files:
            profile_temporary = create_temporary_path(PROFILE_OUTPUT)
            temporary_files.callback(profile_temporary.unlink, missing_ok=True)
            reduced_motion_temporary = create_temporary_path(
                PROFILE_REDUCED_MOTION_OUTPUT
            )
            temporary_files.callback(reduced_motion_temporary.unlink, missing_ok=True)
            favicon_temporary = create_temporary_path(FAVICON_OUTPUT)
            temporary_files.callback(favicon_temporary.unlink, missing_ok=True)

            _build_animated_profile(magick, profile_temporary)
            _build_reduced_motion_profile(magick, reduced_motion_temporary)
            _build_favicon(magick, favicon_temporary)
            _validate_output(profile_temporary)
            _validate_output(reduced_motion_temporary)
            _validate_output(favicon_temporary)
            os.replace(profile_temporary, PROFILE_OUTPUT)
            os.replace(reduced_motion_temporary, PROFILE_REDUCED_MOTION_OUTPUT)
            os.replace(favicon_temporary, FAVICON_OUTPUT)
    except subprocess.CalledProcessError as error:
        print(
            f"Image conversion failed with exit code {error.returncode}.",
            file=sys.stderr,
        )
        return error.returncode or 1
    except RuntimeError as error:
        print(error, file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Unable to build profile media: {error}", file=sys.stderr)
        return 1

    print(f"Built {_display_path(PROFILE_OUTPUT)}")
    print(f"Built {_display_path(PROFILE_REDUCED_MOTION_OUTPUT)}")
    print(f"Built {_display_path(FAVICON_OUTPUT)}")
    return 0


def _build_animated_profile(magick: str, output: Path) -> None:
    """Scale an animation while preserving every resized frame exactly."""

    _run_magick(
        magick,
        str(PROFILE_SOURCE),
        "-coalesce",
        "-resize",
        f"{PROFILE_SIZE}x{PROFILE_SIZE}",
        "-strip",
        *LOSSLESS_WEBP_OPTIONS,
        str(output),
    )


def _build_favicon(magick: str, output: Path) -> None:
    """Extract and scale the animation's first frame as a PNG favicon."""

    _run_magick(
        magick,
        f"{PROFILE_SOURCE}[0]",
        "-resize",
        f"{FAVICON_SIZE}x{FAVICON_SIZE}",
        "-strip",
        str(output),
    )


def _build_reduced_motion_profile(magick: str, output: Path) -> None:
    """Extract a still 256px WebP for people who prefer reduced motion."""

    _run_magick(
        magick,
        f"{PROFILE_SOURCE}[0]",
        "-resize",
        f"{PROFILE_SIZE}x{PROFILE_SIZE}",
        "-strip",
        *LOSSLESS_WEBP_OPTIONS,
        str(output),
    )


def _run_magick(magick: str, *arguments: str) -> None:
    """Run ImageMagick and propagate a conversion failure to the caller."""

    subprocess.run((magick, *arguments), check=True)


def _validate_output(output: Path) -> None:
    """Reject a successful tool invocation that did not create usable media."""

    if not output.is_file() or output.stat().st_size == 0:
        raise RuntimeError(f"ImageMagick did not create a usable asset: {output}")


def _display_path(path: Path) -> Path:
    """Return a project-relative path when possible without rejecting other outputs."""

    return path.relative_to(PROJECT_ROOT) if path.is_relative_to(PROJECT_ROOT) else path


def create_temporary_path(output: Path) -> Path:
    """Create a unique same-directory temporary path with the output suffix."""

    with NamedTemporaryFile(
        dir=output.parent,
        prefix=f".{output.stem}-",
        suffix=output.suffix,
        delete=False,
    ) as temporary_file:
        return Path(temporary_file.name)


if __name__ == "__main__":
    raise SystemExit(main())
