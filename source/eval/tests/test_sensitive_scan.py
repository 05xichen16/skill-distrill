"""Determinism test for the sensitive_scan skill.

Runs the skill's pure-Python scan over the real public archive with OCR
disabled and asserts the boundary-regex text counts and image discovery match
the measured ground truth:
    phone, email, id, key = 2782, 3479, 2299, 3562
    images_total = 6

Fully offline, no network. Standard-library unittest.
"""
from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = REPO_ROOT / "publish" / "publish_V1" / "sensitive_data_2_1.zip"
SKILL_RUN = (
    REPO_ROOT
    / "source"
    / "solution"
    / "skills"
    / "sensitive_scan"
    / "scripts"
    / "run.py"
)

EXPECTED_TEXT = {"phone": 2782, "email": 3479, "id": 2299, "key": 3562}
EXPECTED_IMAGES = 6


def _load_skill_module():
    spec = importlib.util.spec_from_file_location("sensitive_scan_run", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class SensitiveScanDeterministicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.module = _load_skill_module()
        cls.result = cls.module.scan(
            {"zip_path": str(ARCHIVE), "do_ocr": False}
        )

    def test_text_counts_match_ground_truth(self) -> None:
        text = self.result["breakdown"]["text"]
        order = self.module.ORDER  # ("phone", "email", "id", "key")
        got = dict(zip(order, text))
        self.assertEqual(got, EXPECTED_TEXT)

    def test_image_count(self) -> None:
        self.assertEqual(self.result["images_total"], EXPECTED_IMAGES)

    def test_no_ocr_performed_offline(self) -> None:
        # do_ocr=False -> image contributions are all zero and nothing was OCR'd.
        self.assertEqual(self.result["images_ocr_ok"], 0)
        self.assertEqual(self.result["breakdown"]["image"], [0, 0, 0, 0])
        self.assertEqual(
            self.result["breakdown"]["total"],
            self.result["breakdown"]["text"],
        )

    def test_phone_regex_does_not_overcount_inside_ids(self) -> None:
        # The bounded phone regex must not fire on an 11-digit run inside an
        # 18-digit ID; the unbounded version would explode the count.
        self.assertEqual(len(self.module.RE_PHONE.findall("110101199001011234")), 0)
        self.assertEqual(len(self.module.RE_PHONE.findall("13800138000")), 1)

    def test_structured_image_items_are_validated_and_counted(self) -> None:
        content = (
            '```json\n'
            '{"phones":["13800138000","138 0013 8001","not-phone"],'
            '"emails":["a@b.com"],'
            '"ids":["110101199001011234","110101 19900101 123X"],'
            '"api_keys":["sk-abc","sk-abc"]}'
            '\n```'
        )
        items = self.module._parse_image_items(content)
        counts = self.module._count_extracted_items(items)
        self.assertEqual(counts, {"phone": 2, "email": 1, "id": 2, "key": 2})


if __name__ == "__main__":
    unittest.main()
