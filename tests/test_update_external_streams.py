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


if __name__ == "__main__":
    unittest.main()
