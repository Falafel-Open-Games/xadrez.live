import unittest

from scripts.update_external_streams import filter_latest_stream_per_creator, preserve_existing_if_richer


class PreserveExistingStreamMetadataTest(unittest.TestCase):
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

    def test_filters_recent_streams_to_latest_per_creator(self):
        streams = [
            {"creator": "GM Krikor", "url": "old-krikor", "sort_timestamp": 10},
            {"creator": "Everton Togni", "url": "everton", "sort_timestamp": 30},
            {"creator": "GM Krikor", "url": "new-krikor", "sort_timestamp": 20},
        ]

        filtered = filter_latest_stream_per_creator(streams)

        self.assertEqual([stream["url"] for stream in filtered], ["everton", "new-krikor"])


if __name__ == "__main__":
    unittest.main()
