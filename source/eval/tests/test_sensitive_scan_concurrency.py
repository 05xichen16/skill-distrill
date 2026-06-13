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
import os
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
        os.environ["SENSITIVE_SCAN_RETRY_BACKOFF"] = "0"  # keep retry tests fast
        self.addCleanup(os.environ.pop, "SENSITIVE_SCAN_RETRY_BACKOFF", None)
        self.module = _load_skill_module()
        # Pretend the gateway is configured; extract_image_counts is mocked per-test.
        self.module._model_config = lambda: {
            "url": "http://mock",
            "api_key": "k",
            "model": "m",
            "package_id": "",
        }

    def _scan(self, archive_bytes: bytes, tmp_name: str):
        import tempfile

        with tempfile.TemporaryDirectory() as tmp_dir:
            path = os.path.join(tmp_dir, tmp_name)
            with open(path, "wb") as handle:
                handle.write(archive_bytes)
            return self.module.scan({"zip_path": path, "do_ocr": True})

    def test_images_run_concurrently(self) -> None:
        in_flight = {"now": 0, "peak": 0}
        lock = threading.Lock()

        def slow_extract(config, name, data, plan, timeout):
            with lock:
                in_flight["now"] += 1
                in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
            time.sleep(0.2)
            with lock:
                in_flight["now"] -= 1
            return [1, 0, 0, 0]  # phone,email,id,key (default plan order)

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
        def flaky_extract(config, name, data, plan, timeout):
            if name.endswith("img_1.png"):
                raise RuntimeError("gateway boom")
            return [0, 0, 1, 0]  # one id

        self.module.extract_image_counts = flaky_extract
        result = self._scan(_archive_with_images(3), "fail.zip")

        self.assertEqual(result["images_ocr_ok"], 2)
        self.assertEqual(result["breakdown"]["image"][2], 2)  # id counts from 2 ok images
        self.assertTrue(any("img_1.png" in w for w in result["warnings"]))
        # text counts survive regardless of the broken image
        self.assertEqual(result["breakdown"]["text"][0], 1)

    def test_deadline_emits_text_answer_instead_of_hanging(self) -> None:
        # The single most important reliability guarantee: if OCR cannot finish
        # within the runner's kill budget, the skill must still return a
        # well-formed text answer fast (a dropped stdout forces the version-less
        # model loop). Here OCR "hangs" but a near-past deadline cuts it off.
        def hang_extract(config, name, data, plan, timeout):
            time.sleep(5.0)
            return [9, 9, 9, 9]

        self.module.extract_image_counts = hang_extract
        self.module._ocr_deadline = lambda start: time.monotonic() + 0.3

        started = time.monotonic()
        result = self._scan(_archive_with_images(4), "deadline.zip")
        elapsed = time.monotonic() - started

        self.assertLess(elapsed, 3.0)  # did NOT wait for the 5s hangs
        # text counts survive; image counts contributed nothing past the deadline
        self.assertEqual(result["breakdown"]["text"][0], 1)  # note.txt phone
        self.assertEqual(result["images_ocr_ok"], 0)
        self.assertEqual(result["breakdown"]["image"], [0, 0, 0, 0])
        self.assertTrue(any("deadline" in w for w in result["warnings"]))
        # a valid 4-field answer is still produced
        self.assertEqual(len(result["answer"].split(",")), 4)

    def test_retry_recovers_flaky_image(self) -> None:
        attempts = {}
        lock = threading.Lock()

        def flaky_then_ok(config, name, data, plan, timeout):
            with lock:
                attempts[name] = attempts.get(name, 0) + 1
                if attempts[name] == 1:
                    raise RuntimeError("transient")
            return [0, 0, 0, 1]  # one key

        self.module.extract_image_counts = flaky_then_ok
        result = self._scan(_archive_with_images(2), "retry.zip")

        self.assertEqual(result["images_ocr_ok"], 2)
        self.assertEqual(result["breakdown"]["image"][3], 2)
        self.assertEqual(result["warnings"], [])

    def test_storm_recovery_rides_out_prolonged_5xx(self) -> None:
        # The real platform failure: one image keeps returning HTTP 500 during a
        # gateway storm that outlasts the OLD 3-retry budget, then recovers. With
        # "ratio" grading a dropped image zeroes 1-4 fields, so we MUST keep
        # retrying (in rounds) until the storm clears, not give up after 3.
        attempts = {}
        lock = threading.Lock()
        storm_len = 6  # > the old SENSITIVE_SCAN_RETRIES default of 3

        def storm_then_ok(config, name, data, plan, timeout):
            with lock:
                attempts[name] = attempts.get(name, 0) + 1
                n = attempts[name]
            if name.endswith("img_1.png") and n <= storm_len:
                raise RuntimeError("HTTP Error 500: ")
            return [0, 0, 1, 0]  # one id

        self.module.extract_image_counts = storm_then_ok
        result = self._scan(_archive_with_images(3), "storm.zip")

        # Every image is eventually transcribed -> all fields correct, no warning.
        self.assertEqual(result["images_ocr_ok"], 3)
        self.assertEqual(result["breakdown"]["image"][2], 3)  # id from all 3
        self.assertEqual(result["warnings"], [])
        self.assertGreater(attempts["img_1.png"], storm_len)

    def test_concurrency_is_capped_at_workers(self) -> None:
        # We must NOT amplify the storm: peak in-flight OCR calls stay <= workers
        # even when there are many more images than workers.
        os.environ["SENSITIVE_SCAN_WORKERS"] = "2"
        self.addCleanup(os.environ.pop, "SENSITIVE_SCAN_WORKERS", None)
        in_flight = {"now": 0, "peak": 0}
        lock = threading.Lock()

        def slow_ok(config, name, data, plan, timeout):
            with lock:
                in_flight["now"] += 1
                in_flight["peak"] = max(in_flight["peak"], in_flight["now"])
            time.sleep(0.05)
            with lock:
                in_flight["now"] -= 1
            return [1, 0, 0, 0]  # one phone

        self.module.extract_image_counts = slow_ok
        result = self._scan(_archive_with_images(6), "cap.zip")

        self.assertEqual(result["images_ocr_ok"], 6)
        self.assertEqual(result["breakdown"]["image"][0], 6)
        self.assertLessEqual(in_flight["peak"], 2)


if __name__ == "__main__":
    unittest.main()
