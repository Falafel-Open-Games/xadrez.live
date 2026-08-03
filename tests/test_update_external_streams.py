import unittest

from scripts.update_external_streams import (
    LIVE_WINDOW_SECONDS,
    demote_stale_live_item,
    filter_latest_stream_per_creator,
    filter_upcoming_streams,
    preserve_existing_if_richer,
    timestamp_from_title,
)


class PreserveExistingStreamMetadataTest(unittest.TestCase):
    def test_extracts_timestamp_from_youtube_title_date(self):
        timestamp = timestamp_from_title("Xadrezin de Leves 2026-07-31 11:47")

        self.assertGreater(timestamp, 0)

    def test_preserves_richer_existing_metadata_for_flat_playlist_fallback(self):
        existing = {
            "https://www.youtube.com/watch?v=h3cJk0cgiFA": {
                "title": "Live #146 - O guia prático para VENCER as ANTI-SICILIANAS",
                "display_title": "Live #146 - O guia prático para VENCER as ANTI-SICILIANAS",
                "url": "https://www.youtube.com/watch?v=h3cJk0cgiFA",
                "published_at": "2026-06-26T11:07:28+00:00",
                "published_date": "2026-06-26",
                "published_label": "26/06/2026",
                "live_status": "was_live",
                "was_live": "true",
            }
        }
        candidate = {
            "title": "Live #146 - The Practical Guide to BEATING the ANTI-SICILIANS",
            "display_title": "Live #146 - The Practical Guide to BEATING the ANTI-SICILIANS",
            "url": "https://www.youtube.com/watch?v=h3cJk0cgiFA",
            "published_at": "2026-06-25T00:00:00+00:00",
            "published_date": "2026-06-24",
            "published_label": "24/06/2026",
            "live_status": "",
            "was_live": "false",
            "sort_timestamp": 1782345600,
        }

        merged = preserve_existing_if_richer(candidate, existing)

        self.assertEqual(merged["title"], "Live #146 - O guia prático para VENCER as ANTI-SICILIANAS")
        self.assertEqual(merged["published_at"], "2026-06-26T11:07:28+00:00")
        self.assertEqual(merged["live_status"], "was_live")
        self.assertEqual(merged["was_live"], "true")

    def test_live_candidate_wins_over_existing_recent_metadata(self):
        existing = {
            "https://www.youtube.com/watch?v=XrIGxIStS6I": {
                "title": "O CAMPEÃO CHEGOU???????? SESC CAIOBÁ 2026 - RODADA7",
                "display_title": "O campeão chegou? SESC caiobá 2026 - rodada7",
                "url": "https://www.youtube.com/watch?v=XrIGxIStS6I",
                "published_at": "2026-07-03T00:00:00+00:00",
                "published_date": "2026-07-02",
                "published_label": "02/07/2026",
                "live_status": "",
                "was_live": "false",
            }
        }
        candidate = {
            "title": "O CAMPEÃO CHEGOU???????? SESC CAIOBÁ 2026 - RODADA7",
            "display_title": "O campeão chegou? SESC caiobá 2026 - rodada7",
            "url": "https://www.youtube.com/watch?v=XrIGxIStS6I",
            "scheduled_at": "2026-07-03T14:37:47+00:00",
            "scheduled_date": "2026-07-03",
            "scheduled_label": "ao vivo agora",
            "scheduled_time": "",
            "live_status": "is_live",
            "was_live": "false",
            "sort_timestamp": 1783089467,
        }

        merged = preserve_existing_if_richer(candidate, existing)

        self.assertEqual(merged["scheduled_label"], "ao vivo agora")
        self.assertEqual(merged["live_status"], "is_live")
        self.assertNotIn("published_label", merged)

    def test_finished_candidate_wins_over_existing_upcoming_metadata(self):
        existing = {
            "https://www.youtube.com/watch?v=rOYG2AjX594": {
                "title": "Torneio Internacional de Xadrez SESC Caiobá 2026",
                "display_title": "Torneio Internacional de Xadrez SESC Caiobá 2026",
                "url": "https://www.youtube.com/watch?v=rOYG2AjX594",
                "scheduled_at": "2026-07-03T18:15:00+00:00",
                "scheduled_date": "2026-07-03",
                "scheduled_label": "03/07/2026",
                "scheduled_time": "15:15",
                "live_status": "is_upcoming",
                "was_live": "false",
            }
        }
        candidate = {
            "title": "Torneio Internacional de Xadrez SESC Caiobá 2026",
            "display_title": "Torneio Internacional de Xadrez SESC Caiobá 2026",
            "url": "https://www.youtube.com/watch?v=rOYG2AjX594",
            "published_at": "2026-07-03T21:30:00+00:00",
            "published_date": "2026-07-03",
            "published_label": "03/07/2026",
            "duration": "2:42:25",
            "live_status": "was_live",
            "was_live": "true",
            "sort_timestamp": 1783114200,
        }

        merged = preserve_existing_if_richer(candidate, existing)

        self.assertEqual(merged["published_label"], "03/07/2026")
        self.assertEqual(merged["live_status"], "was_live")
        self.assertNotIn("scheduled_label", merged)

    def test_filters_recent_streams_to_latest_per_creator(self):
        streams = [
            {"creator": "GM Krikor", "url": "old-krikor", "sort_timestamp": 10},
            {"creator": "Everton Togni", "url": "everton", "sort_timestamp": 30},
            {"creator": "GM Krikor", "url": "new-krikor", "sort_timestamp": 20},
        ]

        filtered = filter_latest_stream_per_creator(streams)

        self.assertEqual([stream["url"] for stream in filtered], ["everton", "new-krikor"])

    def test_filters_stale_live_streams_from_upcoming(self):
        now = 1_800_000_000
        streams = [
            {
                "creator": "Old Live",
                "url": "old-live",
                "live_status": "is_live",
                "sort_timestamp": now - LIVE_WINDOW_SECONDS - 1,
            },
            {
                "creator": "Fresh Live",
                "url": "fresh-live",
                "live_status": "is_live",
                "sort_timestamp": now - 60,
            },
            {
                "creator": "Upcoming",
                "url": "upcoming",
                "live_status": "is_upcoming",
                "sort_timestamp": now + 60,
            },
        ]

        filtered = filter_upcoming_streams(streams, now)

        self.assertEqual([stream["url"] for stream in filtered], ["fresh-live", "upcoming"])

    def test_demotes_stale_live_metadata_to_recent_status(self):
        now = 1_800_000_000
        item = {
            "live_status": "is_live",
            "was_live": False,
            "release_timestamp": now - LIVE_WINDOW_SECONDS - 1,
        }

        demoted = demote_stale_live_item(item, now)

        self.assertEqual(demoted["live_status"], "was_live")
        self.assertTrue(demoted["was_live"])

    def test_demotes_stale_live_metadata_using_title_timestamp(self):
        now = timestamp_from_title("Any stream 2026-08-02 12:00")
        item = {
            "title": "Xadrezin de Leves 2026-07-31 11:47",
            "live_status": "is_live",
            "was_live": False,
        }

        demoted = demote_stale_live_item(item, now)

        self.assertEqual(demoted["live_status"], "was_live")
        self.assertTrue(demoted["was_live"])


if __name__ == "__main__":
    unittest.main()
