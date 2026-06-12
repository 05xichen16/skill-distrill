"""Concurrent image-extraction behavior tests for the sensitive_scan skill.

The production gateway takes ~50-60s per image; many sequential images can
exceed the skill timeout and the whole scan gets killed. These
tests pin the new behavior with a mocked gateway, fully offline:
  * images are processed concurrently (wall-clock ~ one image, not the sum)
  * one image failing (after retries) degrades to a warning + zero counts
  * retry succeeds on a flaky-then-ok image

Standard-library unittest.
"""
from __future__ import annotations

import importlib.util
import io
import threading
import time
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT
    / "source"
    / "solution"
    / "skills"
    / "sensitive_scan"
    / "scripts"
    / "run.py"
)


def _load_skill_module():
    spec = importlib.util.spec_from_file_location("sensitive_scan_run_conc", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _archive_with_images(count: int) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("note.txt", "phone 13800138000 mail a@b.com")
        for index in range(count):
            archive.writestr("img_%d.png" % index, b"\x89PNG fake image bytes")
    return buffer.getvalue()


class SensitiveScanConcurrencyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_skill_module()
        # Pretend the gateway is configured; extract_image_counts is mocked per-test.
        self.module._model_config = lambda: {
            "url": "http://mock",
            "api_key": "k",
            "model": "m",
            "package_id": "",
        }

    def _scan(self, archive_bytes: bytes, tmp_name: str):
        import tempfile, os

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, tmp_name)
            with open(path, "wb") as handle:
                handle.write(archive_bytes)
            return self.module.scan({"zip_path": path, "do_ocr": True})

    def test_images_run_concurrently(self) -> None:
        in_flight = {"now": 0, "peak": 0}
        lock = threading.Lock()

        def slow_extract(config, name, data, timeout):
            with lock:
                in_flight["now"] += 1
                in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
            time.sleep(0.2)
            with lock:
                in_flight["now"] -= 1
            return {"phone": 1, "email": 0, "id": 0, "key": 0}

        self.module.extract_image_counts = slow_extract
        started = time.monotonic()
        result = self._scan(_archive_with_images(4), "conc.zip")
        elapsed = time.monotonic() - started

        self.assertEqual(result["images_ocr_ok"], 4)
        # 4 images x 0.2s sequentially = 0.8s; concurrent should be well under.
        self.assertLess(elapsed, 0.7)
        self.assertGreaterEqual(in_flight["peak"], 2)
        # each transcription contributed one phone
        self.assertEqual(result["breakdown"]["image"][0], 4)

    def test_single_failure_degrades_not_kills(self) -> None:
        def flaky_extract(config, name, data, timeout):
            if name.endswith("img_1.png"):
                raise RuntimeError("gateway boom")
            return {"phone": 0, "email": 0, "id": 1, "key": 0}

        self.module.extract_image_counts = flaky_extract
        result = self._scan(_archive_with_images(3), "fail.zip")

        self.assertEqual(result["images_ocr_ok"], 2)
        self.assertEqual(result["breakdown"]["image"][2], 2)  # id counts from 2 ok images
        self.assertTrue(any("img_1.png" in w for w in result["warnings"]))
        # text counts survive regardless of the broken image
        self.assertEqual(result["breakdown"]["text"][0], 1)

    def test_retry_recovers_flaky_image(self) -> None:
        attempts = {}
        lock = threading.Lock()

        def flaky_then_ok(config, name, data, timeout):
            with lock:
                attempts[name] = attempts.get(name, 0) + 1
                if attempts[name] == 1:
                    raise RuntimeError("transient")
            return {"phone": 0, "email": 0, "id": 0, "key": 1}

        self.module.extract_image_counts = flaky_then_ok
        result = self._scan(_archive_with_images(2), "retry.zip")

        self.assertEqual(result["images_ocr_ok"], 2)
        self.assertEqual(result["breakdown"]["image"][3], 2)
        self.assertEqual(result["warnings"], [])


if __name__ == "__main__":
    unittest.main()
