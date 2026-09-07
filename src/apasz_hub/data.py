"""Typed metadata and runtime-loaded destination data for the public hub."""

from __future__ import annotations

import os
from dataclasses import dataclass
from enum import StrEnum
from json import JSONDecodeError, loads
from pathlib import Path
from typing import Final, TypedDict, cast
from urllib.parse import urlsplit


class CardTier(StrEnum):
    """Visual prominence levels supported by the homepage."""

    FEATURED = "featured"
    STANDARD = "standard"
    UTILITY = "utility"


class CardKind(StrEnum):
    """Content schemas that add card-specific validation and behavior."""

    NORMAL = "normal"
    MAIL = "mail"
    GITHUB = "github"


@dataclass(frozen=True, slots=True)
class LinkCard:
    """A public destination rendered by the homepage."""

    title: str
    href: str
    tier: CardTier
    icon: str
    description: str | None = None
    border_hover: str | None = None
    icon_scale: int = 100
    border_static: str | None = None
    icon_static: str | None = None
    icon_hover: str | None = None
    metadata: str | None = None
    schema: CardKind = CardKind.NORMAL
    opens_in_new_tab: bool = True
    copy_to_clipboard: bool = False
    copy_text: str | None = None

    def __post_init__(self) -> None:
        if self.icon_scale < 1:
            raise ValueError(f"{self.title} icon scale must be positive.")
        if self.tier is CardTier.FEATURED and not self.metadata:
            raise ValueError(f"Featured card {self.title} must include metadata.")
        self._validate_schema()
        if self.copy_to_clipboard and not (self.copy_text and self.copy_text.strip()):
            raise ValueError(
                f"{self.title} clipboard actions require non-empty copy text."
            )

    def _validate_schema(self) -> None:
        """Validate fields whose requirements depend on the card schema."""

        if self.schema is CardKind.MAIL and not _mailto_recipient(self.href):
            raise ValueError(
                f"Mail card {self.title} requires a non-empty mailto destination."
            )
        if self.schema is CardKind.NORMAL and self.href.lower().startswith("mailto:"):
            raise ValueError(
                f"Normal card {self.title} cannot use a mailto destination."
            )
        if self.schema is CardKind.GITHUB and not _github_profile_login(self.href):
            raise ValueError(
                f"GitHub card {self.title} requires a canonical GitHub profile destination."
            )

    @property
    def github_login(self) -> str:
        """Return the validated GitHub profile login for a GitHub card."""

        if self.schema is not CardKind.GITHUB:
            raise ValueError(f"{self.title} is not configured as a GitHub card.")
        login = _github_profile_login(self.href)
        if not login:
            raise ValueError(
                f"GitHub card {self.title} has an invalid profile destination."
            )
        return login

    @property
    def clipboard_text(self) -> str:
        """Return the configured clipboard value for an enabled action."""

        if not self.copy_to_clipboard or self.copy_text is None:
            raise ValueError(f"{self.title} is not configured as a clipboard action.")
        return self.copy_text


class LinkCardDataError(ValueError):
    """Raised when the editable link-card data file is invalid."""


class _LinkCardOptions(TypedDict, total=False):
    """Optional JSON fields that map directly to ``LinkCard`` defaults."""

    description: str | None
    border_hover: str | None
    icon_scale: int
    border_static: str | None
    icon_static: str | None
    icon_hover: str | None
    metadata: str | None
    schema: CardKind
    opens_in_new_tab: bool
    copy_to_clipboard: bool
    copy_text: str | None


@dataclass(frozen=True, slots=True)
class SiteMetadata:
    """Document metadata shared by public pages."""

    title: str
    description: str
    canonical_url: str


SITE: Final = SiteMetadata(
    title="APasz",
    description="The public APasz hub for code, community, and contact links",
    canonical_url="https://apasz.com/",
)

PROFILE_IMAGE_URL: Final = "/static/media/pfp-anim.webp"
PROFILE_REDUCED_MOTION_IMAGE_URL: Final = "/static/media/pfp-still.webp"
FAVICON_URL: Final = "/static/media/favicon.png"
WORDMARK_URL: Final = "/static/media/wordmark.svg"
SITE_SCRIPT_URL: Final = "/static/site.js"
DEFAULT_LINK_CARDS_PATH: Final = Path(__file__).with_name("link_cards.json")
LINK_CARDS_PATH_ENV: Final = "APASZ_HUB_LINK_CARDS_PATH"

_REQUIRED_CARD_FIELDS: Final = ("title", "href", "tier", "icon")
_OPTIONAL_CARD_FIELDS: Final = frozenset(_LinkCardOptions.__annotations__)
_CARD_FIELDS: Final = frozenset(_REQUIRED_CARD_FIELDS) | _OPTIONAL_CARD_FIELDS


def load_link_cards(path: Path | None = None) -> tuple[LinkCard, ...]:
    """Load and validate the current editable link-card JSON document.

    The file is deliberately read for every homepage render so valid changes take
    effect without restarting the server.
    """

    data_path = _configured_link_cards_path() if path is None else path
    try:
        raw_data = cast(
            object,
            loads(
                data_path.read_text(encoding="utf-8"),
                object_pairs_hook=_reject_duplicate_json_keys,
            ),
        )
    except OSError as error:
        raise LinkCardDataError(
            f"Unable to read link-card data from {data_path}."
        ) from error
    except JSONDecodeError as error:
        raise LinkCardDataError(
            f"Invalid JSON in link-card data file {data_path} at line {error.lineno}, column {error.colno}."
        ) from error
    except UnicodeDecodeError as error:
        raise LinkCardDataError(
            f"Invalid UTF-8 in link-card data file {data_path}."
        ) from error

    if not isinstance(raw_data, list):
        raise LinkCardDataError("Link-card data must be a JSON array.")
    values = cast(list[object], raw_data)
    return tuple(_parse_link_card(value, index) for index, value in enumerate(values))


def cards_for_tier(cards: tuple[LinkCard, ...], tier: CardTier) -> tuple[LinkCard, ...]:
    """Return cards in their configured order for one homepage tier."""

    return tuple(card for card in cards if card.tier is tier)


def _configured_link_cards_path() -> Path:
    """Return the packaged default or an explicitly writable data-file path."""

    configured_path = os.environ.get(LINK_CARDS_PATH_ENV)
    if configured_path is None:
        return DEFAULT_LINK_CARDS_PATH
    configured_path = configured_path.strip()
    if not configured_path:
        raise LinkCardDataError(f"{LINK_CARDS_PATH_ENV} must not be empty.")
    return Path(configured_path)


def _reject_duplicate_json_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    """Build one decoded JSON object while rejecting ambiguous duplicate keys."""

    fields: dict[str, object] = {}
    for name, value in pairs:
        if name in fields:
            raise LinkCardDataError(f"Duplicate JSON field {name!r}.")
        fields[name] = value
    return fields


def _parse_link_card(value: object, index: int) -> LinkCard:
    """Validate one JSON object and convert it to the domain model."""

    context = f"Link card at index {index}"
    fields = _object_fields(value, context)
    unknown_fields = sorted(set(fields) - _CARD_FIELDS)
    if unknown_fields:
        raise LinkCardDataError(
            f"{context} has unsupported field(s): {', '.join(unknown_fields)}."
        )
    missing_fields = [field for field in _REQUIRED_CARD_FIELDS if field not in fields]
    if missing_fields:
        raise LinkCardDataError(
            f"{context} is missing required field(s): {', '.join(missing_fields)}."
        )

    options = _parse_optional_fields(fields, context)
    try:
        return LinkCard(
            title=_required_string(fields, "title", context),
            href=_required_string(fields, "href", context),
            tier=_card_tier(fields, context),
            icon=_required_string(fields, "icon", context),
            **options,
        )
    except ValueError as error:
        raise LinkCardDataError(f"{context} is invalid: {error}") from error


def _object_fields(value: object, context: str) -> dict[str, object]:
    if not isinstance(value, dict):
        raise LinkCardDataError(f"{context} must be a JSON object.")
    fields = cast(dict[object, object], value)
    if not all(isinstance(key, str) for key in fields):
        raise LinkCardDataError(f"{context} must be a JSON object.")
    return cast(dict[str, object], fields)


def _required_string(fields: dict[str, object], name: str, context: str) -> str:
    value = fields[name]
    if not isinstance(value, str) or not value.strip():
        raise LinkCardDataError(f"{context} field {name!r} must be a non-empty string.")
    return value


def _card_tier(fields: dict[str, object], context: str) -> CardTier:
    value = _required_string(fields, "tier", context)
    try:
        return CardTier(value)
    except ValueError as error:
        choices = ", ".join(tier.value for tier in CardTier)
        raise LinkCardDataError(
            f"{context} field 'tier' must be one of: {choices}."
        ) from error


def _card_kind(fields: dict[str, object], context: str) -> CardKind:
    value = _required_string(fields, "schema", context)
    try:
        return CardKind(value)
    except ValueError as error:
        choices = ", ".join(kind.value for kind in CardKind)
        raise LinkCardDataError(
            f"{context} field 'schema' must be one of: {choices}."
        ) from error


def _parse_optional_fields(fields: dict[str, object], context: str) -> _LinkCardOptions:
    options: _LinkCardOptions = {}
    for name in (
        "description",
        "border_hover",
        "border_static",
        "icon_static",
        "icon_hover",
        "metadata",
        "copy_text",
    ):
        if name in fields:
            options[name] = _optional_string(fields[name], name, context)
    if "icon_scale" in fields:
        options["icon_scale"] = _positive_integer(fields["icon_scale"], context)
    if "schema" in fields:
        options["schema"] = _card_kind(fields, context)
    for name in ("opens_in_new_tab", "copy_to_clipboard"):
        if name in fields:
            options[name] = _boolean(fields[name], name, context)
    return options


def _optional_string(value: object, name: str, context: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise LinkCardDataError(
            f"{context} field {name!r} must be a non-empty string or null."
        )
    return value


def _positive_integer(value: object, context: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise LinkCardDataError(
            f"{context} field 'icon_scale' must be a positive integer."
        )
    return value


def _boolean(value: object, name: str, context: str) -> bool:
    if not isinstance(value, bool):
        raise LinkCardDataError(f"{context} field {name!r} must be a boolean.")
    return value


def _mailto_recipient(href: str) -> str:
    """Return the address portion of a mailto URL, if present."""

    if not href.lower().startswith("mailto:"):
        return ""
    return href[len("mailto:") :].partition("?")[0].strip()


def _github_profile_login(href: str) -> str:
    """Return the login from a canonical GitHub profile URL, if valid."""

    try:
        parsed = urlsplit(href)
    except ValueError:
        return ""
    if (
        parsed.scheme.lower() != "https"
        or parsed.netloc.lower() != "github.com"
        or parsed.query
        or parsed.fragment
    ):
        return ""
    login = parsed.path.removeprefix("/").removesuffix("/")
    return login if login and "/" not in login else ""
