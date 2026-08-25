import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import postlive_thumbnail


class PostliveThumbnailTest(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        self.root = Path(self.tmpdir.name)
        self.template = self.root / "template.png"
        self.metadata_dir = self.root / "metadata"
        self.output = self.root / "static" / "fcz" / "thumbnails" / "thumb.jpg"
        self.output.parent.mkdir(parents=True)
        self.template.write_bytes(b"template")
        self.patches = [
            mock.patch.object(postlive_thumbnail, "ROOT", self.root),
            mock.patch.object(postlive_thumbnail, "TEMPLATE", self.template),
            mock.patch.object(postlive_thumbnail, "METADATA_DIR", self.metadata_dir),
        ]
        for patch in self.patches:
            patch.start()
            self.addCleanup(patch.stop)

    def expected(self, prompt="prompt"):
        return postlive_thumbnail.expected_metadata(
            "0071",
            self.output,
            "/fcz/thumbnails/thumb.jpg",
            prompt,
            "gpt-image-2",
            "auto",
            "high",
        )

    def test_existing_legacy_output_with_matching_og_image_skips(self):
        self.output.write_bytes(b"image")

        self.assertTrue(
            postlive_thumbnail.should_skip_generation(
                "0071",
                self.output,
                "/fcz/thumbnails/thumb.jpg",
                {"og_image": "/fcz/thumbnails/thumb.jpg"},
                self.expected(),
                force=False,
            )
        )

    def test_metadata_mismatch_regenerates_even_with_matching_og_image(self):
        self.output.write_bytes(b"image")
        postlive_thumbnail.write_generation_metadata("0071", self.expected(prompt="old prompt"))

        self.assertFalse(
            postlive_thumbnail.should_skip_generation(
                "0071",
                self.output,
                "/fcz/thumbnails/thumb.jpg",
                {"og_image": "/fcz/thumbnails/thumb.jpg"},
                self.expected(prompt="new prompt"),
                force=False,
            )
        )

    def test_force_regenerates_even_when_metadata_matches(self):
        self.output.write_bytes(b"image")
        expected = self.expected()
        postlive_thumbnail.write_generation_metadata("0071", expected)

        self.assertFalse(
            postlive_thumbnail.should_skip_generation(
                "0071",
                self.output,
                "/fcz/thumbnails/thumb.jpg",
                {"og_image": "/fcz/thumbnails/thumb.jpg"},
                expected,
                force=True,
            )
        )


if __name__ == "__main__":
    unittest.main()
