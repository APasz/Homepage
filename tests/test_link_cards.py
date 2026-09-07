"""Tests for the editable JSON link-card data boundary."""

from __future__ import annotations

import asyncio
from json import dumps
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase
from unittest.mock import patch

from apasz_hub.data import (
    LINK_CARDS_PATH_ENV,
    CardKind,
    CardTier,
    LinkCardDataError,
    load_link_cards,
)
from apasz_hub.framework import render
from apasz_hub.github import GithubRepositoryCountCache
from apasz_hub.pages import homepage


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


class LinkCardDataTests(TestCase):
    """Ensure editable JSON becomes validated homepage card data."""

    def test_load_link_cards_applies_model_defaults(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(path, [_card("Example")])

            (card,) = load_link_cards(path)

        self.assertEqual(card.title, "Example")
        self.assertIs(card.tier, CardTier.FEATURED)
        self.assertEqual(card.icon_scale, 100)
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

    def test_homepage_reloads_json_for_each_render(self) -> None:
        with TemporaryDirectory() as temporary_directory:
            path = Path(temporary_directory) / "link_cards.json"
            _write_cards(path, [_card("First destination")])

            with patch.dict(
                "apasz_hub.data.os.environ", {LINK_CARDS_PATH_ENV: str(path)}
            ):
                first_document = render(
                    asyncio.run(homepage(_repository_count_cache()))
                )
                _write_cards(path, [_card("Second destination")])
                second_document = render(
                    asyncio.run(homepage(_repository_count_cache()))
                )

        self.assertIn("First destination", first_document)
        self.assertNotIn("Second destination", first_document)
        self.assertIn("Second destination", second_document)
        self.assertNotIn("First destination", second_document)


async def _unused_repository_count(_: str) -> int:
    raise AssertionError("A normal card configuration must not fetch GitHub data.")


def _repository_count_cache() -> GithubRepositoryCountCache:
    return GithubRepositoryCountCache(_unused_repository_count)
