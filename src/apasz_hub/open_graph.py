"""Persisted Open Graph metadata for shared site previews."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from json import dumps
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlsplit

from apasz_hub import settings
from apasz_hub.data import SiteMetadata
from apasz_hub.json_data import (
    json_object_fields,
    load_json_document,
    write_json_document,
)


class OpenGraphField(StrEnum):
    """Editable fields used to build shared-page metadata."""

    SITE_NAME = "site_name"
    TITLE = "title"
    DESCRIPTION = "description"
    IMAGE_URL = "image_url"


type OpenGraphInputType = Literal["text", "url"]


@dataclass(frozen=True, slots=True)
class OpenGraphFieldDefinition:
    """Validation and presentation details for one Open Graph field."""

    field: OpenGraphField
    label: str
    input_type: OpenGraphInputType
    autocomplete: str
    maximum_length: int
    multiline: bool = False
    required: bool = True
    placeholder: str | None = None


class OpenGraphDataError(ValueError):
    """Raised when persisted or submitted Open Graph data is invalid."""


DEFAULT_OPEN_GRAPH_PATH: Final = Path(__file__).with_name("open_graph.json")
OPEN_GRAPH_PATH_ENV: Final = settings.OPEN_GRAPH_PATH_ENV
OPEN_GRAPH_FIELD_DEFINITIONS: Final[tuple[OpenGraphFieldDefinition, ...]] = (
    OpenGraphFieldDefinition(
        OpenGraphField.SITE_NAME,
        "Site name",
        "text",
        "organization",
        100,
    ),
    OpenGraphFieldDefinition(
        OpenGraphField.TITLE,
        "Title",
        "text",
        "off",
        200,
    ),
    OpenGraphFieldDefinition(
        OpenGraphField.DESCRIPTION,
        "Description",
        "text",
        "off",
        500,
        multiline=True,
    ),
    OpenGraphFieldDefinition(
        OpenGraphField.IMAGE_URL,
        "Image URL",
        "url",
        "url",
        2_048,
        required=False,
        placeholder="https://example.com/share-image.png",
    ),
)

if len(OPEN_GRAPH_FIELD_DEFINITIONS) != len(OpenGraphField) or {
    definition.field for definition in OPEN_GRAPH_FIELD_DEFINITIONS
} != set(OpenGraphField):
    raise RuntimeError("Every Open Graph field must have exactly one definition.")


def load_open_graph_metadata(path: Path | None = None) -> SiteMetadata:
    """Load and validate the persisted Open Graph metadata."""

    data_path = _configured_open_graph_path() if path is None else path
    raw_data = load_json_document(
        data_path,
        data_name="Open Graph data",
        duplicate_field_name="Open Graph field",
        error_type=OpenGraphDataError,
    )
    return _metadata_from_fields(
        json_object_fields(raw_data, "Open Graph data", error_type=OpenGraphDataError)
    )


def save_open_graph_metadata(
    values: Mapping[str, object],
    path: Path | None = None,
) -> SiteMetadata:
    """Validate and atomically persist complete Open Graph metadata."""

    metadata = _metadata_from_fields(values)
    data_path = _configured_open_graph_path() if path is None else path
    document = (
        dumps(
            {
                OpenGraphField.SITE_NAME.value: metadata.site_name,
                OpenGraphField.TITLE.value: metadata.title,
                OpenGraphField.DESCRIPTION.value: metadata.description,
                OpenGraphField.IMAGE_URL.value: metadata.image_url,
            },
            indent=4,
        )
        + "\n"
    )
    write_json_document(
        data_path,
        document,
        data_name="Open Graph data",
        error_type=OpenGraphDataError,
    )
    return metadata


class OpenGraphStore:
    """Keep the published Open Graph metadata in memory while persisting saves."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._published_metadata: SiteMetadata | None = None

    def load(self) -> SiteMetadata:
        """Load the persisted metadata as this process's published snapshot."""

        metadata = load_open_graph_metadata(self._data_path())
        self._published_metadata = metadata
        return metadata

    def published_metadata(self) -> SiteMetadata:
        """Return the in-memory metadata used by rendered pages."""

        self._ensure_loaded()
        metadata = self._published_metadata
        if metadata is None:
            raise RuntimeError("Open Graph store has no published snapshot.")
        return metadata

    def save(self, values: Mapping[str, object]) -> SiteMetadata:
        """Persist valid metadata and publish it to this process."""

        metadata = save_open_graph_metadata(values, self._data_path())
        self._published_metadata = metadata
        return metadata

    def _data_path(self) -> Path:
        """Return the path fixed when this store first accesses its metadata."""

        if self._path is None:
            self._path = _configured_open_graph_path()
        return self._path

    def _ensure_loaded(self) -> None:
        """Provide a safe one-time fallback for direct ASGI use outside lifespan."""

        if self._published_metadata is None:
            self.load()


def open_graph_field_value(metadata: SiteMetadata, field: OpenGraphField) -> str:
    """Return one form-ready value from published Open Graph metadata."""

    if field is OpenGraphField.SITE_NAME:
        return metadata.site_name
    if field is OpenGraphField.TITLE:
        return metadata.title
    if field is OpenGraphField.DESCRIPTION:
        return metadata.description
    if field is OpenGraphField.IMAGE_URL:
        return metadata.image_url or ""
    raise AssertionError(f"Unsupported Open Graph field: {field.value}.")


def _configured_open_graph_path() -> Path:
    """Return the packaged default or explicitly writable metadata file path."""

    configured_path = settings.load_settings().open_graph_path
    if configured_path is None:
        return DEFAULT_OPEN_GRAPH_PATH
    return configured_path


def _metadata_from_fields(values: Mapping[str, object]) -> SiteMetadata:
    expected_names = {
        definition.field.value for definition in OPEN_GRAPH_FIELD_DEFINITIONS
    }
    unknown_names = sorted(set(values) - expected_names)
    if unknown_names:
        raise OpenGraphDataError(
            f"Open Graph data has unsupported field(s): {', '.join(unknown_names)}."
        )
    missing_names = [
        definition.field.value
        for definition in OPEN_GRAPH_FIELD_DEFINITIONS
        if definition.required and definition.field.value not in values
    ]
    if missing_names:
        raise OpenGraphDataError(
            f"Open Graph data is missing required field(s): {', '.join(missing_names)}."
        )

    field_values = {
        definition.field: _validated_field_value(
            values.get(definition.field.value),
            definition,
        )
        for definition in OPEN_GRAPH_FIELD_DEFINITIONS
    }
    return SiteMetadata(
        site_name=_required_field_value(field_values, OpenGraphField.SITE_NAME),
        title=_required_field_value(field_values, OpenGraphField.TITLE),
        description=_required_field_value(field_values, OpenGraphField.DESCRIPTION),
        canonical_url=_canonical_url(),
        image_url=_optional_field_value(field_values, OpenGraphField.IMAGE_URL),
    )


def _validated_field_value(
    value: object | None,
    definition: OpenGraphFieldDefinition,
) -> str | None:
    if value is None and not definition.required:
        return None
    if not isinstance(value, str):
        raise OpenGraphDataError(
            f"Open Graph field {definition.field.value!r} must be text."
        )
    normalised_value = (
        value.strip()
        if definition.field is OpenGraphField.IMAGE_URL
        else " ".join(value.split())
    )
    if any(not character.isprintable() for character in normalised_value):
        raise OpenGraphDataError(
            f"Open Graph field {definition.field.value!r} must not contain "
            "control characters."
        )
    if not normalised_value:
        if definition.required:
            raise OpenGraphDataError(
                f"Open Graph field {definition.field.value!r} must not be empty."
            )
        return None
    if len(normalised_value) > definition.maximum_length:
        raise OpenGraphDataError(
            f"Open Graph field {definition.field.value!r} exceeds its maximum length "
            f"of {definition.maximum_length}."
        )
    if definition.field is OpenGraphField.IMAGE_URL:
        _validate_image_url(normalised_value)
    return normalised_value


def _validate_image_url(value: str) -> None:
    """Require a normal absolute HTTP(S) URL for a shared-preview image."""

    if any(character.isspace() or ord(character) < 32 for character in value):
        raise OpenGraphDataError("Open Graph image URL must not contain whitespace.")
    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError as error:
        raise OpenGraphDataError("Open Graph image URL is invalid.") from error
    if (
        parsed.scheme.casefold() not in {"http", "https"}
        or parsed.hostname is None
        or parsed.netloc.endswith(":")
        or parsed.username is not None
        or parsed.password is not None
    ):
        raise OpenGraphDataError(
            "Open Graph image URL must be an absolute HTTP(S) URL."
        )


def _required_field_value(
    values: Mapping[OpenGraphField, str | None],
    field: OpenGraphField,
) -> str:
    value = values[field]
    if value is None:
        raise RuntimeError(f"Required Open Graph field {field.value} is missing.")
    return value


def _optional_field_value(
    values: Mapping[OpenGraphField, str | None],
    field: OpenGraphField,
) -> str | None:
    return values[field]


def _canonical_url() -> str:
    """Derive the public homepage URL from the configured public origin."""

    return f"{settings.load_settings().public_origin.rstrip('/')}/"
