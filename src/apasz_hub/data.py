"""Typed metadata and runtime-loaded destination data for the public hub."""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from json import dumps
from pathlib import Path
from typing import Final, Literal, TypedDict, cast
from urllib.parse import quote, unquote, urlsplit

from apasz_hub import settings
from apasz_hub.json_data import (
    json_object_fields,
    load_json_document,
    write_json_document,
)
from apasz_hub.theme import ThemeColorToken, is_hex_colour


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


DEFAULT_ICON_SCALE: Final = 100


type LinkCardInputType = Literal["email", "text", "url"]


@dataclass(frozen=True, slots=True)
class LinkCardDestinationSpec:
    """The config-form contract for one schema's destination value."""

    schema_label: str
    label: str
    input_type: LinkCardInputType
    placeholder: str
    autocomplete: str
    pattern: str | None = None


_GITHUB_LOGIN_PATTERN: Final = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?"
)

LINK_CARD_DESTINATION_SPECS: Final[Mapping[CardKind, LinkCardDestinationSpec]] = {
    CardKind.NORMAL: LinkCardDestinationSpec(
        schema_label="Normal",
        label="Destination",
        input_type="url",
        placeholder="https://example.com",
        autocomplete="url",
    ),
    CardKind.MAIL: LinkCardDestinationSpec(
        schema_label="Email",
        label="Email address",
        input_type="email",
        placeholder="hello@example.com",
        autocomplete="email",
    ),
    CardKind.GITHUB: LinkCardDestinationSpec(
        schema_label="GitHub",
        label="GitHub username",
        input_type="text",
        placeholder="octocat",
        autocomplete="username",
        pattern=_GITHUB_LOGIN_PATTERN.pattern,
    ),
}


class LinkCardFormField(StrEnum):
    """Editable LinkCard fields accepted from the configuration form."""

    TITLE = "title"
    DESTINATION = "destination"
    TIER = "tier"
    ICON = "icon"
    DESCRIPTION = "description"
    ICON_SCALE = "icon_scale"
    METADATA = "metadata"
    SCHEMA = "schema"
    OPENS_IN_NEW_TAB = "opens_in_new_tab"
    COPY_TO_CLIPBOARD = "copy_to_clipboard"
    COPY_TEXT = "copy_text"
    BORDER_STATIC = "border_static"
    BORDER_STATIC_AUTO = "border_static_auto"
    BORDER_HOVER = "border_hover"
    BORDER_HOVER_AUTO = "border_hover_auto"
    ICON_STATIC = "icon_static"
    ICON_STATIC_AUTO = "icon_static_auto"
    ICON_HOVER = "icon_hover"
    ICON_HOVER_AUTO = "icon_hover_auto"


LINK_CARD_DELETE_INDEX_FORM_NAME: Final = "link-card-delete-index"


@dataclass(frozen=True, slots=True)
class LinkCardColourControl:
    """Configuration metadata for one optional LinkCard colour override."""

    field: LinkCardFormField
    auto_field: LinkCardFormField
    label: str
    fallback_token: ThemeColorToken


@dataclass(frozen=True, slots=True)
class LinkCardColourControlPair:
    """A compact editor row containing two related colour controls."""

    label: str
    controls: tuple[LinkCardColourControl, LinkCardColourControl]


_BORDER_COLOUR_CONTROLS: Final[LinkCardColourControlPair] = LinkCardColourControlPair(
    label="Border static / hover",
    controls=(
        LinkCardColourControl(
            LinkCardFormField.BORDER_STATIC,
            LinkCardFormField.BORDER_STATIC_AUTO,
            "Border static",
            ThemeColorToken.BORDER,
        ),
        LinkCardColourControl(
            LinkCardFormField.BORDER_HOVER,
            LinkCardFormField.BORDER_HOVER_AUTO,
            "Border hover",
            ThemeColorToken.ACCENT,
        ),
    ),
)
_ICON_COLOUR_CONTROLS: Final[LinkCardColourControlPair] = LinkCardColourControlPair(
    label="Icon static / hover",
    controls=(
        LinkCardColourControl(
            LinkCardFormField.ICON_STATIC,
            LinkCardFormField.ICON_STATIC_AUTO,
            "Icon static",
            ThemeColorToken.ACCENT,
        ),
        LinkCardColourControl(
            LinkCardFormField.ICON_HOVER,
            LinkCardFormField.ICON_HOVER_AUTO,
            "Icon hover",
            ThemeColorToken.ACCENT,
        ),
    ),
)
LINK_CARD_COLOUR_CONTROL_PAIRS: Final[tuple[LinkCardColourControlPair, ...]] = (
    _BORDER_COLOUR_CONTROLS,
    _ICON_COLOUR_CONTROLS,
)
LINK_CARD_COLOUR_CONTROLS: Final[tuple[LinkCardColourControl, ...]] = (
    *(control for pair in LINK_CARD_COLOUR_CONTROL_PAIRS for control in pair.controls),
)


@dataclass(frozen=True, slots=True)
class LinkCard:
    """A public destination rendered by the homepage."""

    title: str
    href: str
    tier: CardTier
    icon: str
    description: str | None = None
    border_hover: str | None = None
    icon_scale: int = DEFAULT_ICON_SCALE
    border_static: str | None = None
    icon_static: str | None = None
    icon_hover: str | None = None
    metadata: str | None = None
    schema: CardKind = CardKind.NORMAL
    opens_in_new_tab: bool = True
    copy_to_clipboard: bool = False
    copy_text: str | None = None

    def __post_init__(self) -> None:
        if type(self.icon_scale) is not int or self.icon_scale < 1:
            raise ValueError(f"{self.title} icon scale must be positive.")
        if self.tier is CardTier.FEATURED and not self.metadata:
            raise ValueError(f"Featured card {self.title} must include metadata.")
        self._validate_schema()
        self._validate_icon()
        self._validate_colour_overrides()
        if self.copy_to_clipboard and not (self.copy_text and self.copy_text.strip()):
            raise ValueError(
                f"{self.title} clipboard actions require non-empty copy text."
            )

    def _validate_schema(self) -> None:
        """Validate fields whose requirements depend on the card schema."""

        if self.schema is CardKind.NORMAL and not _is_https_url(self.href):
            raise ValueError(
                f"Normal card {self.title} requires an absolute HTTPS destination."
            )
        if self.schema is CardKind.MAIL and not _is_email_address(
            _mailto_recipient(self.href)
        ):
            raise ValueError(
                f"Mail card {self.title} requires a mailto destination with an email address."
            )
        if self.schema is CardKind.GITHUB and not _github_profile_login(self.href):
            raise ValueError(
                f"GitHub card {self.title} requires a canonical GitHub profile destination."
            )

    def _validate_icon(self) -> None:
        """Restrict card masks to an available local SVG asset."""

        if not _is_available_icon_url(self.icon):
            raise ValueError(f"{self.title} icon must be an available local SVG asset.")

    def _validate_colour_overrides(self) -> None:
        """Keep optional card-specific colour overrides picker-compatible."""

        for label, value in (
            ("border static", self.border_static),
            ("border hover", self.border_hover),
            ("icon static", self.icon_static),
            ("icon hover", self.icon_hover),
        ):
            if value is not None and not is_hex_colour(value):
                raise ValueError(
                    f"{self.title} {label} colour must be a six-digit hex value."
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


def link_card_colour_override(
    card: LinkCard,
    field: LinkCardFormField,
) -> str | None:
    """Return one custom card colour selected by its editable form field."""

    if field is LinkCardFormField.BORDER_STATIC:
        return card.border_static
    if field is LinkCardFormField.BORDER_HOVER:
        return card.border_hover
    if field is LinkCardFormField.ICON_STATIC:
        return card.icon_static
    if field is LinkCardFormField.ICON_HOVER:
        return card.icon_hover
    raise AssertionError(f"{field.value} is not a LinkCard colour field.")


@dataclass(frozen=True, slots=True)
class IconAsset:
    """A publicly served SVG icon available to the LinkCard editor."""

    name: str
    url: str


class LinkCardDataError(ValueError):
    """Raised when persisted or draft LinkCard data is invalid."""


class LinkCardDraftConflictError(RuntimeError):
    """Raised when an outdated request attempts to overwrite the card draft."""


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
    canonical_url=f"{settings.DEFAULT_PUBLIC_ORIGIN}/",
)


def _versioned_static_url(filename: str) -> str:
    """Return a content-versioned URL so browsers cannot reuse stale site code."""

    asset_path = Path(__file__).with_name("static") / filename
    try:
        version = sha256(asset_path.read_bytes()).hexdigest()[:12]
    except OSError as error:
        raise RuntimeError(f"Unable to read static asset {asset_path}.") from error
    return f"/static/{filename}?v={version}"


PROFILE_IMAGE_URL: Final = "/static/media/pfp-anim.webp"
PROFILE_REDUCED_MOTION_IMAGE_URL: Final = "/static/media/pfp-still.webp"
FAVICON_URL: Final = "/static/media/favicon.png"
WORDMARK_URL: Final = "/static/media/wordmark.svg"
SITE_STYLESHEET_URL: Final = _versioned_static_url("site.css")
SITE_SCRIPT_URL: Final = _versioned_static_url("site.js")
DEFAULT_LINK_CARDS_PATH: Final = Path(__file__).with_name("link_cards.json")
LINK_CARDS_PATH_ENV: Final = settings.LINK_CARDS_PATH_ENV
ICON_DIRECTORY: Final = Path(__file__).with_name("static") / "icons"
ICON_URL_PREFIX: Final = "/static/icons"


def _is_https_url(value: str) -> bool:
    """Whether a normal-card destination is a safe absolute HTTPS URL."""

    try:
        parsed = urlsplit(value)
        _ = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme.casefold() == "https"
        and parsed.hostname is not None
        and parsed.username is None
        and parsed.password is None
        and not any(character.isspace() or ord(character) < 32 for character in value)
    )


def _is_available_icon_url(value: str) -> bool:
    """Whether a card icon identifies exactly one SVG in the local icon directory."""

    try:
        parsed = urlsplit(value)
    except ValueError:
        return False
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment:
        return False
    prefix = f"{ICON_URL_PREFIX}/"
    if not parsed.path.startswith(prefix):
        return False
    filename = unquote(parsed.path.removeprefix(prefix))
    if (
        not filename
        or Path(filename).name != filename
        or "\\" in filename
        or Path(filename).suffix.casefold() != ".svg"
        or any(character.isspace() or ord(character) < 32 for character in filename)
    ):
        return False
    return (ICON_DIRECTORY / filename).is_file()


DEFAULT_NEW_LINK_CARD: Final = LinkCard(
    title="New Link",
    href="https://example.com",
    tier=CardTier.STANDARD,
    icon=f"{ICON_URL_PREFIX}/github.svg",
)

_REQUIRED_CARD_FIELDS: Final = ("title", "href", "tier", "icon")
_OPTIONAL_CARD_FIELDS: Final = frozenset(_LinkCardOptions.__annotations__)
_CARD_FIELDS: Final = frozenset(_REQUIRED_CARD_FIELDS) | _OPTIONAL_CARD_FIELDS


def load_link_cards(path: Path | None = None) -> tuple[LinkCard, ...]:
    """Load and validate the persisted link-card JSON document."""

    data_path = _configured_link_cards_path() if path is None else path
    raw_data = load_json_document(
        data_path,
        data_name="link-card data",
        duplicate_field_name="JSON field",
        error_type=LinkCardDataError,
    )

    if not isinstance(raw_data, list):
        raise LinkCardDataError("Link-card data must be a JSON array.")
    values = cast(list[object], raw_data)
    return tuple(_parse_link_card(value, index) for index, value in enumerate(values))


def load_icon_assets() -> tuple[IconAsset, ...]:
    """Return every locally served SVG icon in deterministic filename order."""

    try:
        paths = sorted(
            (
                path
                for path in ICON_DIRECTORY.iterdir()
                if path.is_file() and path.suffix.lower() == ".svg"
            ),
            key=lambda path: path.name.casefold(),
        )
    except OSError as error:
        raise RuntimeError(
            f"Unable to list local SVG icons in {ICON_DIRECTORY}."
        ) from error
    return tuple(
        IconAsset(
            name=path.name,
            url=f"{ICON_URL_PREFIX}/{quote(path.name)}",
        )
        for path in paths
    )


def save_link_cards(
    cards: tuple[LinkCard, ...],
    path: Path | None = None,
) -> tuple[LinkCard, ...]:
    """Atomically persist a validated LinkCard collection as JSON."""

    data_path = _configured_link_cards_path() if path is None else path
    document = (
        dumps(
            [_link_card_json_fields(card) for card in cards],
            indent=4,
        )
        + "\n"
    )
    write_json_document(
        data_path,
        document,
        data_name="link-card data",
        error_type=LinkCardDataError,
    )
    return cards


def link_card_form_name(index: int, field: LinkCardFormField) -> str:
    """Return the stable HTML form name for one editable card field."""

    if index < 0:
        raise ValueError("Link-card form indexes must not be negative.")
    return f"link-card-{index}-{field.value}"


def link_card_form_destination(card: LinkCard, schema: CardKind) -> str:
    """Return a card's concise editable destination for a selected schema."""

    if schema is CardKind.NORMAL:
        return "" if card.href.lower().startswith("mailto:") else card.href
    if schema is CardKind.MAIL:
        return _mailto_recipient(card.href)
    if schema is CardKind.GITHUB:
        return _github_profile_login(card.href)
    raise AssertionError(f"Unsupported link-card schema: {schema}.")


def link_card_draft_from_form(
    values: Mapping[str, object],
    source_cards: tuple[LinkCard, ...],
    *,
    excluded_index: int | None = None,
) -> tuple[LinkCard, ...]:
    """Validate editor data and return the next draft, optionally omitting a card."""

    if excluded_index is not None:
        _validate_link_card_draft_index(excluded_index, source_cards)

    expected_names: set[str] = set()
    draft_cards: list[LinkCard] = []
    for index in range(len(source_cards)):
        field_names = {
            field: link_card_form_name(index, field) for field in LinkCardFormField
        }
        expected_names.update(field_names.values())
        if index == excluded_index:
            continue
        draft_cards.append(
            _link_card_from_form_fields(
                values,
                field_names,
                index,
            )
        )

    unknown_names = sorted(set(values) - expected_names)
    if unknown_names:
        raise LinkCardDataError(
            f"Link-card draft has unsupported field(s): {', '.join(unknown_names)}."
        )
    return tuple(draft_cards)


def _validate_link_card_draft_index(
    index: int,
    cards: tuple[LinkCard, ...],
) -> None:
    """Ensure an index identifies one card in a draft snapshot."""

    if type(index) is not int:
        raise LinkCardDataError("Link-card draft index must be an integer.")
    if index < 0 or index >= len(cards):
        raise LinkCardDataError(f"Link-card draft index {index} is out of range.")


class LinkCardStore:
    """Keep separate published and editable LinkCard snapshots in one process."""

    def __init__(self, path: Path | None = None) -> None:
        self._path = path
        self._published_cards: tuple[LinkCard, ...] | None = None
        self._draft_cards: tuple[LinkCard, ...] | None = None
        self._draft_revision = 0

    def load(self) -> tuple[LinkCard, ...]:
        """Load the persisted snapshot and reset the in-memory draft to it."""

        if self._path is None:
            self._path = _configured_link_cards_path()
        cards = load_link_cards(self._path)
        self._published_cards = cards
        self._draft_cards = cards
        self._draft_revision += 1
        return cards

    def published_cards(self) -> tuple[LinkCard, ...]:
        """Return the saved in-memory snapshot used by the public homepage."""

        self._ensure_loaded()
        cards = self._published_cards
        if cards is None:
            raise RuntimeError("Link-card store has no published snapshot.")
        return cards

    def draft_cards(self) -> tuple[LinkCard, ...]:
        """Return the in-memory draft displayed and edited on the config page."""

        self._ensure_loaded()
        cards = self._draft_cards
        if cards is None:
            raise RuntimeError("Link-card store has no draft snapshot.")
        return cards

    @property
    def is_draft_dirty(self) -> bool:
        """Whether the editable draft differs from the published snapshot."""

        return self.draft_cards() != self.published_cards()

    @property
    def draft_revision(self) -> int:
        """Return the version used to reject stale asynchronous draft updates."""

        self._ensure_loaded()
        return self._draft_revision

    def update_draft(
        self,
        values: Mapping[str, object],
        *,
        expected_revision: int | None = None,
    ) -> tuple[LinkCard, ...]:
        """Replace the draft only after a complete submitted form validates."""

        source_cards = self.draft_cards()
        if expected_revision is not None and expected_revision != self.draft_revision:
            raise LinkCardDraftConflictError(
                "Link-card draft changed elsewhere; reload the configuration page."
            )
        cards = link_card_draft_from_form(values, source_cards)
        return self._replace_draft_if_changed(source_cards, cards)

    def add_draft_card(self) -> tuple[LinkCard, ...]:
        """Append a valid default card to the editable, unpublished draft."""

        source_cards = self.draft_cards()
        cards = (*source_cards, DEFAULT_NEW_LINK_CARD)
        return self._replace_draft_if_changed(source_cards, cards)

    def add_draft_card_from_form(
        self,
        values: Mapping[str, object],
    ) -> tuple[LinkCard, ...]:
        """Apply valid form edits while atomically appending a default card."""

        source_cards = self.draft_cards()
        draft_cards = link_card_draft_from_form(values, source_cards)
        cards = (*draft_cards, DEFAULT_NEW_LINK_CARD)
        return self._replace_draft_if_changed(source_cards, cards)

    def delete_draft_card(self, index: int) -> tuple[LinkCard, ...]:
        """Remove one card from the editable, unpublished draft."""

        source_cards = self.draft_cards()
        _validate_link_card_draft_index(index, source_cards)
        cards = source_cards[:index] + source_cards[index + 1 :]
        return self._replace_draft_if_changed(source_cards, cards)

    def delete_draft_card_from_form(
        self,
        values: Mapping[str, object],
        index: int,
    ) -> tuple[LinkCard, ...]:
        """Apply valid remaining form edits while atomically discarding one card."""

        source_cards = self.draft_cards()
        cards = link_card_draft_from_form(
            values,
            source_cards,
            excluded_index=index,
        )
        return self._replace_draft_if_changed(source_cards, cards)

    def save_draft(self) -> tuple[LinkCard, ...]:
        """Persist the draft and make it the homepage's published snapshot."""

        cards = self.draft_cards()
        save_link_cards(cards, self._path)
        self._published_cards = cards
        self._draft_revision += 1
        return cards

    def _ensure_loaded(self) -> None:
        """Provide a safe one-time fallback for direct ASGI use outside lifespan."""

        if self._published_cards is None or self._draft_cards is None:
            self.load()

    def _replace_draft_if_changed(
        self,
        source_cards: tuple[LinkCard, ...],
        draft_cards: tuple[LinkCard, ...],
    ) -> tuple[LinkCard, ...]:
        """Store a changed draft snapshot and advance its revision once."""

        if draft_cards != source_cards:
            self._draft_cards = draft_cards
            self._draft_revision += 1
        return draft_cards


def cards_for_tier(cards: tuple[LinkCard, ...], tier: CardTier) -> tuple[LinkCard, ...]:
    """Return cards in their configured order for one homepage tier."""

    return tuple(card for card in cards if card.tier is tier)


def _link_card_json_fields(card: LinkCard) -> dict[str, object]:
    """Return the compact persisted representation for a validated LinkCard."""

    fields: dict[str, object] = {
        "title": card.title,
        "href": card.href,
        "tier": card.tier.value,
        "icon": card.icon,
    }
    optional_values = (
        ("description", card.description),
        ("border_hover", card.border_hover),
        (
            "icon_scale",
            card.icon_scale if card.icon_scale != DEFAULT_ICON_SCALE else None,
        ),
        ("border_static", card.border_static),
        ("icon_static", card.icon_static),
        ("icon_hover", card.icon_hover),
        ("metadata", card.metadata),
        ("schema", card.schema.value if card.schema is not CardKind.NORMAL else None),
        (
            "opens_in_new_tab",
            card.opens_in_new_tab if not card.opens_in_new_tab else None,
        ),
        (
            "copy_to_clipboard",
            card.copy_to_clipboard if card.copy_to_clipboard else None,
        ),
        ("copy_text", card.copy_text),
    )
    fields.update((name, value) for name, value in optional_values if value is not None)
    return fields


def _link_card_from_form_fields(
    values: Mapping[str, object],
    field_names: Mapping[LinkCardFormField, str],
    index: int,
) -> LinkCard:
    """Build one validated draft card from its editable form controls."""

    context = f"Link-card draft at position {index + 1}"
    try:
        colour_overrides = _form_link_card_colour_overrides(
            values,
            field_names,
            context,
        )
        schema = _form_card_kind(
            values,
            field_names[LinkCardFormField.SCHEMA],
            context,
        )
        return LinkCard(
            title=_required_form_string(
                values,
                field_names[LinkCardFormField.TITLE],
                LinkCardFormField.TITLE,
                context,
            ),
            href=_href_from_form_destination(
                schema,
                _required_form_string(
                    values,
                    field_names[LinkCardFormField.DESTINATION],
                    LinkCardFormField.DESTINATION,
                    context,
                ),
            ),
            tier=_form_card_tier(
                values,
                field_names[LinkCardFormField.TIER],
                context,
            ),
            icon=_required_form_string(
                values,
                field_names[LinkCardFormField.ICON],
                LinkCardFormField.ICON,
                context,
            ),
            description=_optional_form_string(
                values,
                field_names[LinkCardFormField.DESCRIPTION],
                LinkCardFormField.DESCRIPTION,
                context,
            ),
            border_hover=colour_overrides[LinkCardFormField.BORDER_HOVER],
            icon_scale=_form_positive_integer(
                values,
                field_names[LinkCardFormField.ICON_SCALE],
                context,
            ),
            border_static=colour_overrides[LinkCardFormField.BORDER_STATIC],
            icon_static=colour_overrides[LinkCardFormField.ICON_STATIC],
            icon_hover=colour_overrides[LinkCardFormField.ICON_HOVER],
            metadata=_optional_form_string(
                values,
                field_names[LinkCardFormField.METADATA],
                LinkCardFormField.METADATA,
                context,
            ),
            schema=schema,
            opens_in_new_tab=_form_boolean(
                values,
                field_names[LinkCardFormField.OPENS_IN_NEW_TAB],
                LinkCardFormField.OPENS_IN_NEW_TAB,
                context,
            ),
            copy_to_clipboard=_form_boolean(
                values,
                field_names[LinkCardFormField.COPY_TO_CLIPBOARD],
                LinkCardFormField.COPY_TO_CLIPBOARD,
                context,
            ),
            copy_text=_optional_form_string(
                values,
                field_names[LinkCardFormField.COPY_TEXT],
                LinkCardFormField.COPY_TEXT,
                context,
            ),
        )
    except ValueError as error:
        raise LinkCardDataError(f"{context} is invalid: {error}") from error


def _form_link_card_colour_overrides(
    values: Mapping[str, object],
    field_names: Mapping[LinkCardFormField, str],
    context: str,
) -> dict[LinkCardFormField, str | None]:
    """Read each card colour override, with checked Auto controls as ``None``."""

    return {
        control.field: _form_link_card_colour_override(
            values,
            field_names[control.field],
            field_names[control.auto_field],
            control,
            context,
        )
        for control in LINK_CARD_COLOUR_CONTROLS
    }


def _form_link_card_colour_override(
    values: Mapping[str, object],
    name: str,
    auto_name: str,
    control: LinkCardColourControl,
    context: str,
) -> str | None:
    """Read one explicit colour or an automatic shared-palette fallback."""

    if _form_boolean(values, auto_name, control.auto_field, context):
        return None
    value = _required_form_string(values, name, control.field, context)
    if not is_hex_colour(value):
        raise LinkCardDataError(
            f"{context} field {control.field.value!r} must be a six-digit hex value."
        )
    return value


def _href_from_form_destination(schema: CardKind, destination: str) -> str:
    """Build a canonical stored href from one schema-specific form value."""

    destination = destination.strip()
    if schema is CardKind.NORMAL:
        return destination
    if schema is CardKind.MAIL:
        if destination.lower().startswith("mailto:") or not _is_email_address(
            destination
        ):
            raise ValueError(
                "Mail destination must be an email address without the 'mailto:' prefix."
            )
        return f"mailto:{destination}"
    if schema is CardKind.GITHUB:
        if not _is_github_login(destination):
            raise ValueError("GitHub destination must be a GitHub username.")
        return f"https://github.com/{destination}"
    raise AssertionError(f"Unsupported link-card schema: {schema}.")


def _required_form_string(
    values: Mapping[str, object],
    name: str,
    field: LinkCardFormField,
    context: str,
) -> str:
    """Read one required string input from a card editor form."""

    value = values.get(name)
    if not isinstance(value, str) or not value.strip():
        raise LinkCardDataError(
            f"{context} field {field.value!r} must be a non-empty string."
        )
    return value


def _optional_form_string(
    values: Mapping[str, object],
    name: str,
    field: LinkCardFormField,
    context: str,
) -> str | None:
    """Read one optional string input, normalising blank controls to ``None``."""

    value = values.get(name, "")
    if not isinstance(value, str):
        raise LinkCardDataError(f"{context} field {field.value!r} must be a string.")
    return value if value.strip() else None


def _form_positive_integer(
    values: Mapping[str, object],
    name: str,
    context: str,
) -> int:
    """Read a positive integer input from a card editor form."""

    value = _required_form_string(values, name, LinkCardFormField.ICON_SCALE, context)
    try:
        integer = int(value)
    except ValueError as error:
        raise LinkCardDataError(
            f"{context} field 'icon_scale' must be a positive integer."
        ) from error
    if integer < 1:
        raise LinkCardDataError(
            f"{context} field 'icon_scale' must be a positive integer."
        )
    return integer


def _form_card_tier(
    values: Mapping[str, object],
    name: str,
    context: str,
) -> CardTier:
    """Read a valid card tier from a card editor form."""

    value = _required_form_string(values, name, LinkCardFormField.TIER, context)
    try:
        return CardTier(value)
    except ValueError as error:
        choices = ", ".join(tier.value for tier in CardTier)
        raise LinkCardDataError(
            f"{context} field 'tier' must be one of: {choices}."
        ) from error


def _form_card_kind(
    values: Mapping[str, object],
    name: str,
    context: str,
) -> CardKind:
    """Read a valid card schema from a card editor form."""

    value = _required_form_string(values, name, LinkCardFormField.SCHEMA, context)
    try:
        return CardKind(value)
    except ValueError as error:
        choices = ", ".join(kind.value for kind in CardKind)
        raise LinkCardDataError(
            f"{context} field 'schema' must be one of: {choices}."
        ) from error


def _form_boolean(
    values: Mapping[str, object],
    name: str,
    field: LinkCardFormField,
    context: str,
) -> bool:
    """Read an optional checkbox, treating an absent control as false."""

    value = values.get(name)
    if value is None:
        return False
    if value != "true":
        raise LinkCardDataError(f"{context} field {field.value!r} must be a boolean.")
    return True


def _configured_link_cards_path() -> Path:
    """Return the packaged default or an explicitly writable data-file path."""

    configured_path = settings.load_settings().link_cards_path
    if configured_path is None:
        return DEFAULT_LINK_CARDS_PATH
    return configured_path


def _parse_link_card(value: object, index: int) -> LinkCard:
    """Validate one JSON object and convert it to the domain model."""

    context = f"Link card at index {index}"
    fields = json_object_fields(value, context, error_type=LinkCardDataError)
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


def _is_email_address(value: str) -> bool:
    """Whether a concise mail destination has one non-empty local and domain part."""

    local_part, separator, domain = value.partition("@")
    return (
        bool(local_part)
        and bool(separator)
        and bool(domain)
        and "@" not in domain
        and not any(character.isspace() for character in value)
    )


def _is_github_login(value: str) -> bool:
    """Whether a value follows GitHub's username format."""

    return _GITHUB_LOGIN_PATTERN.fullmatch(value) is not None


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
    return login if _is_github_login(login) else ""
