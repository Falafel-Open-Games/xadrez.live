import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import align_transcript_timestamps


class AlignTranscriptTimestampsArgsTest(unittest.TestCase):
    def test_parse_args_accepts_unpadded_session_number(self):
        with mock.patch("sys.argv", ["align_transcript_timestamps.py", "65"]):
            args = align_transcript_timestamps.parse_args()

        self.assertEqual(args.sessions, ["0065"])


if __name__ == "__main__":
    unittest.main()
