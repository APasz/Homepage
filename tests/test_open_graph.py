"""Tests for persisted Open Graph metadata."""

from __future__ import annotations

import os
from json import dumps
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from apasz_hub.open_graph import (
    DEFAULT_OPEN_GRAPH_PATH,
    OPEN_GRAPH_PATH_ENV,
    OpenGraphDataError,
    OpenGraphField,
    OpenGraphStore,
    load_open_graph_metadata,
    save_open_graph_metadata,
)
from apasz_hub.settings import SettingsValidationError


def _metadata_values() -> dict[str, object]:
    """Return a complete copy of the checked-in Open Graph fields."""

    metadata = load_open_graph_metadata()
    return {
        OpenGraphField.SITE_NAME.value: metadata.site_name,
        OpenGraphField.TITLE.value: metadata.title,
        OpenGraphField.DESCRIPTION.value: metadata.description,
        OpenGraphField.IMAGE_URL.value: metadata.image_url,
    }


class OpenGraphDataTests(TestCase):
    """Keep social sharing metadata strict, persistent, and render-ready."""

    def test_save_replaces_complete_metadata(self) -> None:
        values = _metadata_values()
        values.update(
            {
                OpenGraphField.SITE_NAME.value: "APasz Studio",
                OpenGraphField.TITLE.value: "APasz Studio on the web",
                OpenGraphField.DESCRIPTION.value: "Code, community, and contact.",
                OpenGraphField.IMAGE_URL.value: "https://example.com/share.png",
            }
        )

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "open_graph.json"
            metadata = save_open_graph_metadata(values, path)
            saved_document = path.read_text(encoding="utf-8")

        self.assertEqual(saved_document, dumps(values, indent=4) + "\n")
        self.assertEqual(metadata.site_name, "APasz Studio")
        self.assertEqual(metadata.title, "APasz Studio on the web")
        self.assertEqual(metadata.description, "Code, community, and contact.")
        self.assertEqual(metadata.image_url, "https://example.com/share.png")

    def test_load_rejects_duplicate_incomplete_and_invalid_metadata(self) -> None:
        cases = (
            (
                "duplicate",
                (
                    '{"site_name":"APasz","site_name":"Other",'
                    '"title":"APasz","description":"Description",'
                    '"image_url":null}'
                ),
                "Duplicate Open Graph field 'site_name'",
            ),
            (
                "missing",
                dumps({OpenGraphField.TITLE.value: "APasz"}),
                "missing required field",
            ),
            (
                "unknown",
                dumps({**_metadata_values(), "brand": "APasz"}),
                "unsupported field",
            ),
            (
                "invalid image",
                dumps(
                    {
                        **_metadata_values(),
                        OpenGraphField.IMAGE_URL.value: "ftp://example.com/share.png",
                    }
                ),
                "absolute HTTP",
            ),
            (
                "empty image port",
                dumps(
                    {
                        **_metadata_values(),
                        OpenGraphField.IMAGE_URL.value: "https://example.com:",
                    }
                ),
                "absolute HTTP",
            ),
            (
                "control character",
                dumps(
                    {
                        **_metadata_values(),
                        OpenGraphField.TITLE.value: "Invalid\u0000 title",
                    }
                ),
                "must not contain control characters",
            ),
        )

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "open_graph.json"
            for name, document, message in cases:
                with self.subTest(name=name):
                    path.write_text(document, encoding="utf-8")
                    with self.assertRaisesRegex(OpenGraphDataError, message):
                        load_open_graph_metadata(path)

    def test_load_allows_an_omitted_optional_image_url(self) -> None:
        values = _metadata_values()
        values.pop(OpenGraphField.IMAGE_URL.value)

        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "open_graph.json"
            path.write_text(dumps(values), encoding="utf-8")

            metadata = load_open_graph_metadata(path)

        self.assertIsNone(metadata.image_url)

    def test_store_keeps_the_published_snapshot_when_json_changes_externally(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "open_graph.json"
            path.write_text(
                DEFAULT_OPEN_GRAPH_PATH.read_text(encoding="utf-8"),
                encoding="utf-8",
            )
            store = OpenGraphStore(path)
            published_metadata = store.load()

            changed_values = _metadata_values()
            changed_values[OpenGraphField.TITLE.value] = "External edit"
            path.write_text(dumps(changed_values), encoding="utf-8")

            self.assertEqual(store.published_metadata(), published_metadata)

            path.write_text("{not valid JSON", encoding="utf-8")

        self.assertEqual(store.published_metadata(), published_metadata)

    def test_store_saves_to_the_path_loaded_at_startup(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            startup_path = directory / "startup_open_graph.json"
            changed_path = directory / "changed_open_graph.json"
            startup_values = _metadata_values()
            changed_values = {
                **startup_values,
                OpenGraphField.TITLE.value: "Changed path",
            }
            startup_path.write_text(dumps(startup_values), encoding="utf-8")
            changed_path.write_text(dumps(changed_values), encoding="utf-8")

            with patch.dict(os.environ, {OPEN_GRAPH_PATH_ENV: str(startup_path)}):
                store = OpenGraphStore()
                store.load()
            saved_values = _metadata_values()
            saved_values[OpenGraphField.TITLE.value] = "Saved startup path"

            with patch.dict(os.environ, {OPEN_GRAPH_PATH_ENV: str(changed_path)}):
                store.save(saved_values)

            saved_startup_metadata = load_open_graph_metadata(startup_path)
            unchanged_changed_metadata = load_open_graph_metadata(changed_path)

        self.assertEqual(saved_startup_metadata.title, "Saved startup path")
        self.assertEqual(unchanged_changed_metadata.title, "Changed path")

    def test_empty_path_override_fails_loudly(self) -> None:
        with (
            patch.dict(os.environ, {OPEN_GRAPH_PATH_ENV: "   "}),
            self.assertRaisesRegex(
                SettingsValidationError,
                f"{OPEN_GRAPH_PATH_ENV}: must not be empty",
            ),
        ):
            load_open_graph_metadata()
