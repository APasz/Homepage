"""Strict JSON parsing helpers for editable application data."""

from __future__ import annotations

import os
from collections.abc import Callable
from contextlib import suppress
from json import JSONDecodeError, loads
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import cast


def load_json_document[DataError: ValueError](
    path: Path,
    *,
    data_name: str,
    duplicate_field_name: str,
    error_type: type[DataError],
) -> object:
    """Load one UTF-8 JSON document while rejecting duplicate object fields."""

    try:
        return cast(
            object,
            loads(
                path.read_text(encoding="utf-8"),
                object_pairs_hook=_duplicate_field_rejecter(
                    duplicate_field_name,
                    error_type,
                ),
            ),
        )
    except OSError as error:
        raise error_type(f"Unable to read {data_name} from {path}.") from error
    except JSONDecodeError as error:
        raise error_type(
            f"Invalid JSON in {data_name} file {path} at line {error.lineno}, "
            f"column {error.colno}."
        ) from error
    except UnicodeDecodeError as error:
        raise error_type(f"Invalid UTF-8 in {data_name} file {path}.") from error


def json_object_fields[DataError: ValueError](
    value: object,
    context: str,
    *,
    error_type: type[DataError],
) -> dict[str, object]:
    """Return string-keyed fields from a decoded JSON object."""

    if not isinstance(value, dict):
        raise error_type(f"{context} must be a JSON object.")
    fields = cast(dict[object, object], value)
    if not all(isinstance(name, str) for name in fields):
        raise error_type(f"{context} must be a JSON object.")
    return cast(dict[str, object], fields)


def write_json_document[DataError: ValueError](
    path: Path,
    document: str,
    *,
    data_name: str,
    error_type: type[DataError],
) -> None:
    """Atomically replace a JSON document without leaving partial data behind."""

    temporary_path: Path | None = None
    try:
        with NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
            delete=False,
        ) as temporary_file:
            temporary_path = Path(temporary_file.name)
            temporary_file.write(document)
            temporary_file.flush()
            os.fsync(temporary_file.fileno())
        temporary_path.replace(path)
    except OSError as error:
        raise error_type(f"Unable to write {data_name} to {path}.") from error
    finally:
        if temporary_path is not None:
            with suppress(OSError):
                temporary_path.unlink(missing_ok=True)


def _duplicate_field_rejecter[DataError: ValueError](
    duplicate_field_name: str,
    error_type: type[DataError],
) -> Callable[[list[tuple[str, object]]], dict[str, object]]:
    """Build the JSON object hook that rejects ambiguous duplicate fields."""

    def reject_duplicate_fields(pairs: list[tuple[str, object]]) -> dict[str, object]:
        fields: dict[str, object] = {}
        for name, value in pairs:
            if name in fields:
                raise error_type(f"Duplicate {duplicate_field_name} {name!r}.")
            fields[name] = value
        return fields

    return reject_duplicate_fields
