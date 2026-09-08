"""Tests for the editable JSON link-card data boundary."""

from __future__ import annotations

from dataclasses import replace
from json import dumps
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from apasz_hub.data import (
    DEFAULT_ICON_SCALE,
    LINK_CARDS_PATH_ENV,
    CardKind,
    CardTier,
    LinkCard,
    LinkCardDataError,
    LinkCardDraftConflictError,
    LinkCardFormField,
    LinkCardStore,
    link_card_draft_from_form,
    link_card_form_name,
    load_link_cards,
)
from tests.link_card_form_data import link_card_form_values


def _card(title: str) -> dict[str, object]:
    return {
        "title": title,
        "href": "https://example.com",
        "tier": "featured",
        "description": "Example destination",
        "icon": "/static/icons/github.svg",
        "metadata": "EXAMPLE",
    }


def _write_cards(path: Path, cards: list[dict[str, object]]) -> None:
    path.write_text(dumps(cards), encoding="utf-8")


def _schema_cards() -> tuple[LinkCard, LinkCard]:
    """Return one GitHub and one email card for schema-editor checks."""

    return (
        LinkCard(
            title="GitHub",
            href="https://github.com/APasz",
            tier=CardTier.FEATURED,
            icon="/static/icons/github.svg",
            metadata="GITHUB",
            schema=CardKind.GITHUB,
        ),
        LinkCard(
            title="Email",
            href="mailto:mail@apasz.com",
            tier=CardTier.UTILITY,
            icon="/static/icons/mail.svg",
            schema=CardKind.MAIL,
        ),
    )


class LinkCardDataTests(TestCase):
    """Ensure editable JSON becomes validated homepage card data."""

    def test_load_link_cards_applies_model_defaults(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(path, [_card("Example")])

            (card,) = load_link_cards(path)

        self.assertEqual(card.title, "Example")
        self.assertIs(card.tier, CardTier.FEATURED)
        self.assertEqual(card.icon_scale, DEFAULT_ICON_SCALE)
        self.assertIs(card.schema, CardKind.NORMAL)
        self.assertTrue(card.opens_in_new_tab)
        self.assertFalse(card.copy_to_clipboard)
        self.assertIsNone(card.copy_text)

    def test_load_link_cards_allows_a_missing_description(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            card_data = _card("Example")
            del card_data["description"]
            _write_cards(path, [card_data])

            (card,) = load_link_cards(path)

        self.assertIsNone(card.description)

    def test_load_link_cards_rejects_invalid_schema(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            invalid_card = _card("Example")
            invalid_card["tier"] = "prominent"
            _write_cards(path, [invalid_card])

            with self.assertRaisesRegex(LinkCardDataError, "field 'tier'"):
                load_link_cards(path)

    def test_load_link_cards_rejects_an_unknown_card_kind(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            invalid_card = _card("Example")
            invalid_card["schema"] = "gitlab"
            _write_cards(path, [invalid_card])

            with self.assertRaisesRegex(LinkCardDataError, "field 'schema'"):
                load_link_cards(path)

    def test_load_link_cards_rejects_an_invalid_card_colour(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            invalid_card = _card("Example")
            invalid_card["border_static"] = "purple"
            _write_cards(path, [invalid_card])

            with self.assertRaisesRegex(LinkCardDataError, "border static colour"):
                load_link_cards(path)

    def test_load_link_cards_accepts_a_github_profile_schema(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            github_card = _card("GitHub")
            github_card["href"] = "https://github.com/APasz"
            github_card["schema"] = "github"
            _write_cards(path, [github_card])

            (card,) = load_link_cards(path)

        self.assertIs(card.schema, CardKind.GITHUB)
        self.assertEqual(card.github_login, "APasz")

    def test_draft_canonicalises_schema_specific_destinations(self) -> None:
        cards = _schema_cards()
        values = link_card_form_values(cards)
        github_destination = link_card_form_name(0, LinkCardFormField.DESTINATION)
        email_destination = link_card_form_name(1, LinkCardFormField.DESTINATION)

        self.assertEqual(values[github_destination], "APasz")
        self.assertEqual(values[email_destination], "mail@apasz.com")
        values[github_destination] = "octocat"
        values[email_destination] = "hello@example.com"

        github, email = link_card_draft_from_form(values, cards)

        self.assertEqual(github.href, "https://github.com/octocat")
        self.assertEqual(email.href, "mailto:hello@example.com")

    def test_draft_rejects_prefixed_schema_destinations(self) -> None:
        cards = _schema_cards()
        values = link_card_form_values(cards)
        github_destination = link_card_form_name(0, LinkCardFormField.DESTINATION)
        email_destination = link_card_form_name(1, LinkCardFormField.DESTINATION)
        values[github_destination] = "https://github.com/octocat"

        with self.assertRaisesRegex(LinkCardDataError, "GitHub username"):
            link_card_draft_from_form(values, cards)

        values[github_destination] = "octocat"
        values[email_destination] = "mailto:hello@example.com"

        with self.assertRaisesRegex(LinkCardDataError, "without the 'mailto:' prefix"):
            link_card_draft_from_form(values, cards)

    def test_draft_updates_card_colour_overrides_and_auto_values(self) -> None:
        github, email = _schema_cards()
        cards = (
            replace(
                github,
                border_static="#101112",
                border_hover="#131415",
                icon_static="#161718",
                icon_hover="#191a1b",
            ),
            email,
        )
        values = link_card_form_values(cards)
        border_static = link_card_form_name(
            0,
            LinkCardFormField.BORDER_STATIC,
        )
        icon_hover_auto = link_card_form_name(
            0,
            LinkCardFormField.ICON_HOVER_AUTO,
        )
        values[border_static] = "#abcdef"
        values[icon_hover_auto] = "true"

        draft, _ = link_card_draft_from_form(values, cards)

        self.assertEqual(draft.border_static, "#abcdef")
        self.assertEqual(draft.border_hover, "#131415")
        self.assertEqual(draft.icon_static, "#161718")
        self.assertIsNone(draft.icon_hover)

    def test_draft_rejects_an_invalid_card_colour(self) -> None:
        cards = _schema_cards()
        values = link_card_form_values(cards)
        border_static = link_card_form_name(
            0,
            LinkCardFormField.BORDER_STATIC,
        )
        border_static_auto = link_card_form_name(
            0,
            LinkCardFormField.BORDER_STATIC_AUTO,
        )
        del values[border_static_auto]
        values[border_static] = "#nothex"

        with self.assertRaisesRegex(LinkCardDataError, "six-digit hex"):
            link_card_draft_from_form(values, cards)

    def test_load_link_cards_requires_copy_text_for_clipboard_actions(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            invalid_card = _card("Example")
            invalid_card["copy_to_clipboard"] = True
            _write_cards(path, [invalid_card])

            with self.assertRaisesRegex(
                LinkCardDataError, "require non-empty copy text"
            ):
                load_link_cards(path)

    def test_load_link_cards_rejects_duplicate_json_fields(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            path.write_text(
                """[
                    {
                        "title": "First title",
                        "title": "Second title",
                        "href": "https://example.com",
                        "tier": "featured",
                        "description": "Example destination",
                        "icon": "/static/icons/github.svg",
                        "metadata": "EXAMPLE"
                    }
                ]""",
                encoding="utf-8",
            )

            with self.assertRaisesRegex(
                LinkCardDataError, "Duplicate JSON field 'title'"
            ):
                load_link_cards(path)

    def test_load_link_cards_rejects_an_empty_path_override(self) -> None:
        with (
            patch.dict("apasz_hub.data.os.environ", {LINK_CARDS_PATH_ENV: "   "}),
            self.assertRaisesRegex(
                LinkCardDataError, f"{LINK_CARDS_PATH_ENV} must not be empty"
            ),
        ):
            load_link_cards()

    def test_store_keeps_the_startup_snapshot_when_json_changes_externally(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(path, [_card("First destination")])
            store = LinkCardStore(path)
            store.load()

            _write_cards(path, [_card("Second destination")])

        self.assertEqual(store.published_cards()[0].title, "First destination")
        self.assertEqual(store.draft_cards()[0].title, "First destination")

    def test_store_persists_only_when_its_draft_is_saved(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            card_data = _card("Published destination")
            card_data["border_hover"] = "#123456"
            _write_cards(path, [card_data])
            store = LinkCardStore(path)
            store.load()
            values = link_card_form_values(store.draft_cards())
            values[link_card_form_name(0, LinkCardFormField.TITLE)] = (
                "Draft destination"
            )

            store.update_draft(values)
            before_save = load_link_cards(path)
            store.save_draft()
            after_save = load_link_cards(path)

        self.assertEqual(store.published_cards()[0].title, "Draft destination")
        self.assertFalse(store.is_draft_dirty)
        self.assertEqual(store.draft_cards()[0].border_hover, "#123456")
        self.assertEqual(before_save[0].title, "Published destination")
        self.assertEqual(after_save[0].title, "Draft destination")
        self.assertEqual(after_save[0].border_hover, "#123456")

    def test_store_adds_an_unpublished_default_card(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(path, [_card("Published destination")])
            store = LinkCardStore(path)
            published_cards = store.load()
            draft_revision = store.draft_revision

            draft_cards = store.add_draft_card()

        added_card = draft_cards[-1]
        self.assertEqual(draft_cards[:-1], published_cards)
        self.assertEqual(added_card.title, "New Link")
        self.assertEqual(added_card.href, "https://example.com")
        self.assertIs(added_card.tier, CardTier.STANDARD)
        self.assertEqual(added_card.icon, "/static/icons/github.svg")
        self.assertEqual(store.published_cards(), published_cards)
        self.assertTrue(store.is_draft_dirty)
        self.assertEqual(store.draft_revision, draft_revision + 1)

    def test_store_adds_a_card_from_form_in_one_draft_revision(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(path, [_card("Published destination")])
            store = LinkCardStore(path)
            published_cards = store.load()
            draft_revision = store.draft_revision
            values = link_card_form_values(published_cards)
            values[link_card_form_name(0, LinkCardFormField.TITLE)] = "Changed"

            draft_cards = store.add_draft_card_from_form(values)

        self.assertEqual(draft_cards[0].title, "Changed")
        self.assertEqual(draft_cards[-1].title, "New Link")
        self.assertEqual(store.draft_revision, draft_revision + 1)

    def test_store_deletes_an_unpublished_card(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(
                path,
                [_card("First destination"), _card("Second destination")],
            )
            store = LinkCardStore(path)
            published_cards = store.load()
            draft_revision = store.draft_revision

            draft_cards = store.delete_draft_card(0)

        self.assertEqual(draft_cards, (published_cards[1],))
        self.assertEqual(store.published_cards(), published_cards)
        self.assertTrue(store.is_draft_dirty)
        self.assertEqual(store.draft_revision, draft_revision + 1)
        with self.assertRaisesRegex(LinkCardDataError, "index 1"):
            store.delete_draft_card(1)

    def test_store_deletes_an_invalid_target_card_from_form(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(
                path,
                [_card("First destination"), _card("Second destination")],
            )
            store = LinkCardStore(path)
            published_cards = store.load()
            values = link_card_form_values(published_cards)
            values[link_card_form_name(1, LinkCardFormField.DESTINATION)] = ""

            draft_cards = store.delete_draft_card_from_form(values, 1)

        self.assertEqual(draft_cards, (published_cards[0],))
        self.assertEqual(store.published_cards(), published_cards)
        self.assertTrue(store.is_draft_dirty)

    def test_store_rejects_an_invalid_form_deletion_without_mutating_draft(
        self,
    ) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(path, [_card("Published destination")])
            store = LinkCardStore(path)
            published_cards = store.load()
            values = link_card_form_values(published_cards)
            values[link_card_form_name(0, LinkCardFormField.TITLE)] = "Changed"

            with self.assertRaisesRegex(LinkCardDataError, "index 1"):
                store.delete_draft_card_from_form(values, 1)

        self.assertEqual(store.draft_cards(), published_cards)
        self.assertEqual(store.published_cards(), published_cards)

    def test_store_rejects_a_negative_delete_index(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(path, [_card("Published destination")])
            store = LinkCardStore(path)
            store.load()

            with self.assertRaisesRegex(LinkCardDataError, "index -1"):
                store.delete_draft_card(-1)

    def test_store_rejects_an_outdated_draft_update(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(path, [_card("Published destination")])
            store = LinkCardStore(path)
            store.load()
            expected_revision = store.draft_revision
            values = link_card_form_values(store.draft_cards())
            values[link_card_form_name(0, LinkCardFormField.TITLE)] = (
                "Draft destination"
            )

            store.update_draft(values, expected_revision=expected_revision)
            stale_revision = store.draft_revision
            store.save_draft()

            with self.assertRaises(LinkCardDraftConflictError):
                store.update_draft(values, expected_revision=stale_revision)

        self.assertEqual(store.published_cards()[0].title, "Draft destination")

    def test_store_saves_to_the_path_loaded_at_startup(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            startup_path = directory / "startup_link_cards.json"
            changed_path = directory / "changed_link_cards.json"
            _write_cards(startup_path, [_card("Startup destination")])
            _write_cards(changed_path, [_card("Changed destination")])

            with patch.dict(
                "apasz_hub.data.os.environ",
                {LINK_CARDS_PATH_ENV: str(startup_path)},
            ):
                store = LinkCardStore()
                store.load()
            values = link_card_form_values(store.draft_cards())
            values[link_card_form_name(0, LinkCardFormField.TITLE)] = "Saved draft"

            with patch.dict(
                "apasz_hub.data.os.environ",
                {LINK_CARDS_PATH_ENV: str(changed_path)},
            ):
                store.update_draft(values)
                store.save_draft()
            saved_startup_cards = load_link_cards(startup_path)
            unchanged_changed_cards = load_link_cards(changed_path)

        self.assertEqual(saved_startup_cards[0].title, "Saved draft")
        self.assertEqual(unchanged_changed_cards[0].title, "Changed destination")
