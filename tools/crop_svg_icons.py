"""Crop local SVG icon canvases to their visible drawings with Inkscape."""

from __future__ import annotations

import argparse
import os
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path
from tempfile import NamedTemporaryFile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
ICON_DIRECTORY = PROJECT_ROOT / "src" / "apasz_hub" / "static" / "icons"


class IconCropError(Exception):
    """Raised when an icon cannot be safely cropped."""


def _arguments(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Crop SVG icon viewboxes to their visible drawings.",
    )
    parser.add_argument(
        "icons",
        metavar="ICON",
        nargs="*",
        help="SVG files beneath src/apasz_hub/static/icons; omit to crop all icons.",
    )
    return parser.parse_args(argv)


def _icon_paths(raw_paths: Sequence[str]) -> tuple[Path, ...]:
    """Resolve requested icons and keep writes inside the icon asset directory."""

    candidates = (
        tuple(ICON_DIRECTORY.glob("*.svg"))
        if not raw_paths
        else tuple(Path(raw_path) for raw_path in raw_paths)
    )
    resolved_paths: list[Path] = []
    icon_root = ICON_DIRECTORY.resolve()

    for candidate in candidates:
        path = candidate.resolve()
        if path.suffix.lower() != ".svg":
            raise IconCropError(f"Expected an SVG file: {candidate}")
        if not path.is_relative_to(icon_root):
            raise IconCropError(f"Icon must be inside {ICON_DIRECTORY}: {candidate}")
        if not path.is_file():
            raise IconCropError(f"Icon does not exist: {candidate}")
        resolved_paths.append(path)

    if not resolved_paths:
        raise IconCropError(f"No SVG icons found in {ICON_DIRECTORY}")
    return tuple(sorted(resolved_paths))


def _crop_icon(icon_path: Path, *, inkscape: str) -> None:
    """Replace one icon atomically after Inkscape crops its drawing bounds."""

    with NamedTemporaryFile(
        dir=icon_path.parent,
        suffix=".svg",
        prefix=f".{icon_path.stem}-crop-",
        delete=False,
    ) as temporary_file:
        cropped_path = Path(temporary_file.name)

    try:
        result = subprocess.run(
            (
                inkscape,
                "--export-area-drawing",
                "--export-plain-svg",
                "--export-overwrite",
                f"--export-filename={cropped_path}",
                str(icon_path),
            ),
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise IconCropError(
                f"Inkscape failed for {icon_path.name}: {result.stderr.strip()}"
            )
        if not cropped_path.is_file() or cropped_path.stat().st_size == 0:
            raise IconCropError(
                f"Inkscape did not produce a usable SVG for {icon_path.name}"
            )
        os.replace(cropped_path, icon_path)
    finally:
        cropped_path.unlink(missing_ok=True)


def main(argv: Sequence[str] | None = None) -> int:
    """Crop requested icon files and return a conventional process status."""

    arguments = _arguments(argv)
    inkscape = shutil.which("inkscape")
    if inkscape is None:
        print("Inkscape is required to crop SVG icons.", file=sys.stderr)
        return 2

    try:
        icon_paths = _icon_paths(arguments.icons)
        for icon_path in icon_paths:
            _crop_icon(icon_path, inkscape=inkscape)
            print(f"cropped {icon_path.relative_to(PROJECT_ROOT)}")
    except IconCropError as error:
        print(error, file=sys.stderr)
        return 1
    except OSError as error:
        print(f"Unable to crop SVG icons: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
