"""Offline tests for ContestantAgent image-injection routing.

A declared *directory* (a dataset task such as 3_1's training/validation
folders) must NOT be auto-injected into the agent context by default - those
images are routed to a skill that walks them one-by-one. Injecting the first
few both truncates the set and tempts the model to answer off the partial
sample. A directly-declared image file is still injected as before.

``AGENT_DEMO_INJECT_DIR_IMAGES=1`` restores the legacy directory-walk.

Fully offline: ``_image_blocks`` only base64-encodes bytes (it never decodes
the image), so a tiny fixed byte blob with the right suffix is enough.
Standard-library unittest.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from source.solution.contestant_agent import ContestantAgent

# ``_image_blocks`` only reads bytes and base64-encodes them; the content does
# not have to be a valid image, only the suffix matters for discovery.
_TINY_PNG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])

_DIR_FLAG = "AGENT_DEMO_INJECT_DIR_IMAGES"


class _StubContext:
    """Minimal stand-in: ``_image_blocks`` only touches allowed_file_paths."""

    def __init__(self, allowed_file_paths):
        self.allowed_file_paths = list(allowed_file_paths)


class ImageInjectionRoutingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = ContestantAgent()
        # Start from a known state regardless of the ambient environment.
        os.environ.pop(_DIR_FLAG, None)

    def tearDown(self) -> None:
        os.environ.pop(_DIR_FLAG, None)

    def test_declared_directory_not_injected_by_default(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "images"
            data_dir.mkdir()
            for stem in ("1", "2", "3"):
                (data_dir / ("%s.png" % stem)).write_bytes(_TINY_PNG)

            ctx = _StubContext([data_dir])
            blocks = self.agent._image_blocks(ctx)
            self.assertEqual(blocks, [])

    def test_declared_directory_injected_when_flag_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "images"
            data_dir.mkdir()
            for stem in ("1", "2", "3"):
                (data_dir / ("%s.png" % stem)).write_bytes(_TINY_PNG)

            os.environ[_DIR_FLAG] = "1"
            ctx = _StubContext([data_dir])
            blocks = self.agent._image_blocks(ctx)
            self.assertEqual(len(blocks), 3)
            self.assertTrue(all(b["type"] == "image_url" for b in blocks))

    def test_directly_declared_image_file_still_injected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            image_path = Path(tmp) / "pic.png"
            image_path.write_bytes(_TINY_PNG)

            ctx = _StubContext([image_path])
            blocks = self.agent._image_blocks(ctx)
            self.assertEqual(len(blocks), 1)
            self.assertEqual(blocks[0]["type"], "image_url")
            self.assertTrue(
                blocks[0]["image_url"]["url"].startswith("data:image/png;base64,")
            )

    def test_mixed_directory_and_file_injects_only_the_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp) / "images"
            data_dir.mkdir()
            (data_dir / "1.png").write_bytes(_TINY_PNG)
            (data_dir / "2.png").write_bytes(_TINY_PNG)
            image_path = Path(tmp) / "pic.jpg"
            image_path.write_bytes(_TINY_PNG)

            ctx = _StubContext([data_dir, image_path])
            blocks = self.agent._image_blocks(ctx)
            # Default: directory skipped, only the standalone file injected.
            self.assertEqual(len(blocks), 1)
            self.assertTrue(
                blocks[0]["image_url"]["url"].startswith("data:image/jpeg;base64,")
            )


if __name__ == "__main__":
    unittest.main()
