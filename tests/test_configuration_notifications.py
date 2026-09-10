"""Tests for the friendly configuration-change email summaries."""

from __future__ import annotations

from dataclasses import replace
from unittest import TestCase

from apasz_hub.configuration_notifications import (
    link_cards_notification_detail,
    open_graph_notification_detail,
    theme_colors_notification_detail,
)
from apasz_hub.data import DEFAULT_NEW_LINK_CARD, SiteMetadata
from apasz_hub.theme import load_theme_colors


class ConfigurationNotificationTests(TestCase):
    """Keep configuration email summaries accurate, compact, and readable."""

    def test_theme_summary_lists_before_and_after_values(self) -> None:
        previous = load_theme_colors()
        current = (replace(previous[0], value="#123456"), *previous[1:])

        self.assertEqual(
            theme_colors_notification_detail(previous, current),
            "Your site colours are live.\n\nWhat changed:\n"
            f"- Canvas: {previous[0].value} -> #123456",
        )

    def test_theme_summary_limits_large_saves(self) -> None:
        previous = load_theme_colors()
        current = tuple(
            replace(color, value=f"#{index + 1:06x}")
            for index, color in enumerate(previous)
        )

        detail = theme_colors_notification_detail(previous, current)

        self.assertEqual(detail.count("\n- "), 9)
        self.assertIn("- …and 4 more.", detail)

    def test_open_graph_summary_shows_changed_public_values(self) -> None:
        previous = SiteMetadata(
            site_name="APasz",
            title="APasz",
            description="The original description.",
            canonical_url="https://hub.example.com/",
        )
        current = replace(
            previous,
            title="A better title",
            image_url="https://example.com/share.png",
        )

        self.assertEqual(
            open_graph_notification_detail(previous, current),
            "Your sharing info is live.\n\nWhat changed:\n"
            '- Title: "APasz" -> "A better title"\n'
            '- Image URL: not set -> "https://example.com/share.png"',
        )

    def test_link_card_summary_describes_edits_without_dumping_every_field(
        self,
    ) -> None:
        previous = (replace(DEFAULT_NEW_LINK_CARD, title="Docs"),)
        current = (
            replace(
                previous[0],
                title="Guides",
                description="Helpful information.",
            ),
        )

        self.assertEqual(
            link_cards_notification_detail(previous, current),
            "Your link cards are live.\n\nWhat changed:\n"
            '- Renamed "Docs" -> "Guides"; also updated description.',
        )

    def test_link_card_summary_describes_additions_removals_and_reordering(
        self,
    ) -> None:
        first = replace(DEFAULT_NEW_LINK_CARD, title="Docs")
        second = replace(DEFAULT_NEW_LINK_CARD, title="Status")

        self.assertEqual(
            link_cards_notification_detail((first,), (first, second)),
            'Your link cards are live.\n\nWhat changed:\n- Added: "Status".',
        )
        self.assertEqual(
            link_cards_notification_detail((first, second), (first,)),
            'Your link cards are live.\n\nWhat changed:\n- Removed: "Status".',
        )
        self.assertEqual(
            link_cards_notification_detail((first, second), (second, first)),
            "Your link cards are live.\n\nWhat changed:\n- Card order changed.",
        )

    def test_unchanged_save_says_so(self) -> None:
        cards = (DEFAULT_NEW_LINK_CARD,)

        self.assertEqual(
            link_cards_notification_detail(cards, cards),
            "Your link cards are live.\n\n"
            "Nothing actually changed — it was just saved again.",
        )
