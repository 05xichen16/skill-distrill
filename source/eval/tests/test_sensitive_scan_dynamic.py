"""Dynamic-category (variant) tests for the sensitive_scan skill.

The public set asks for exactly four sensitive types (phone,email,id,key) but the
platform variant's own spec says "敏感信息类型可能增加" and is graded positionally
+ exactly ("ratio"). The skill therefore reads the ORDERED output-field list from
the question description at runtime instead of hardcoding four columns. These
tests pin that behaviour, fully offline (no live model):

  * the four known categories always reuse the validated regexes and make ZERO
    model calls -- the common run is byte-for-byte unchanged;
  * a genuinely new category (e.g. 银行卡号) gets its own detector, is counted,
    and is emitted in the right position WITHOUT disturbing the known columns;
  * the field ORDER follows the description;
  * a missing/garbled output-format line falls back to the four-category default;
  * a new category with no usable detector degrades to a 0 count that still keeps
    its position (strictly better than a wrong-arity answer).

Standard-library unittest.
"""
from __future__ import annotations

import importlib.util
import io
import os
import re
import tempfile
import unittest
import zipfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
ARCHIVE = REPO_ROOT / "publish" / "publish_V1" / "sensitive_data_2_1.zip"
SKILL_RUN = (
    REPO_ROOT / "source" / "solution" / "skills" / "sensitive_scan" / "scripts" / "run.py"
)

# The public 4-category output-format line, verbatim shape.
DESC_4 = (
    "请扫描压缩包内所有文件中的敏感信息，敏感信息类型包括：\n"
    "1) 手机号：以1开头的11位数字\n"
    "2) 邮箱地址：满足user@domain.com格式\n"
    "3) 身份证号：18位，最后一位可能为X\n"
    "4) API Key：以sk-开头的字符串\n"
    "请输出敏感信息计数，输出格式为'手机号,邮箱,身份证,APIKey'，用英文逗号分隔。"
)

# A variant that ADDS a fifth category (bank card) -- the exact scenario the 188
# uncounted 16-digit numbers in the public data foreshadow.
DESC_5_BANK = DESC_4.replace(
    "4) API Key：以sk-开头的字符串\n",
    "4) API Key：以sk-开头的字符串\n5) 银行卡号：16到19位数字\n",
).replace("'手机号,邮箱,身份证,APIKey'", "'手机号,邮箱,身份证,APIKey,银行卡号'")

EXPECTED_TEXT_PUBLIC = [2782, 3479, 2299, 3562]


def _load_skill_module():
    spec = importlib.util.spec_from_file_location("sensitive_scan_dynamic", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _block(phones=0, emails=0, ids=0, keys=0, banks=0):
    """Text with EXACTLY the requested count of each token, isolated per line so
    the boundary regexes never cross-match.

    Lengths are distinct (phone=11, id=18, bank=16) so the bounded regexes count
    independently: a 16-digit card is never an 18-digit id and never an 11-digit
    phone, and vice versa.
    """
    lines = []
    for i in range(phones):
        lines.append("phone: 13%09d" % i)          # 1-led, 11 digits
    for i in range(emails):
        lines.append("mail: user%d@example.com" % i)
    for i in range(ids):
        lines.append("id: 4101%014d" % i)           # 18 digits
    for i in range(keys):
        lines.append("key: sk-%032d" % i)
    for i in range(banks):
        lines.append("card: 62%014d" % i)           # 16 digits
    return "\n".join(lines) + "\n"


class ParseAndMapTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_skill_module()

    def test_parse_output_fields_public_four(self):
        self.assertEqual(
            self.module.parse_output_fields(DESC_4),
            ["手机号", "邮箱", "身份证", "APIKey"],
        )

    def test_parse_output_fields_variant_five(self):
        self.assertEqual(
            self.module.parse_output_fields(DESC_5_BANK),
            ["手机号", "邮箱", "身份证", "APIKey", "银行卡号"],
        )

    def test_parse_output_fields_preserves_reordered(self):
        desc = "输出格式为'邮箱,手机号,APIKey,身份证'，用英文逗号分隔。"
        self.assertEqual(
            self.module.parse_output_fields(desc),
            ["邮箱", "手机号", "APIKey", "身份证"],
        )

    def test_parse_output_fields_handles_curly_quotes(self):
        desc = "输出格式为‘手机号,邮箱’。"
        self.assertEqual(self.module.parse_output_fields(desc), ["手机号", "邮箱"])

    def test_parse_output_fields_none_when_no_format_line(self):
        self.assertIsNone(self.module.parse_output_fields("扫描压缩包统计敏感信息。"))
        self.assertIsNone(self.module.parse_output_fields(""))

    def test_match_known_key(self):
        m = self.module.match_known_key
        self.assertEqual(m("手机号"), "phone")
        self.assertEqual(m("邮箱地址"), "email")
        self.assertEqual(m("身份证号"), "id")
        self.assertEqual(m("API Key"), "key")
        self.assertEqual(m("APIKey"), "key")
        # genuinely new categories map to nothing -> custom detector path
        self.assertIsNone(m("银行卡号"))
        self.assertIsNone(m("家庭住址"))
        self.assertIsNone(m("姓名"))

    def test_safe_compile(self):
        sc = self.module._safe_compile
        self.assertIsNotNone(sc(r"(?<!\d)\d{16}(?!\d)"))
        self.assertIsNotNone(sc("```regex\n(?<!\\d)\\d{16}(?!\\d)\n```"))  # fenced
        self.assertIsNotNone(sc("'sk-\\S+'"))  # surrounding quotes stripped
        self.assertIsNone(sc(""))
        self.assertIsNone(sc("(unbalanced"))         # does not compile
        self.assertIsNone(sc(r"\d*"))                # matches empty string -> rejected
        self.assertIsNone(sc("x" * 500))             # absurdly long -> rejected


class BuildPlanTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_skill_module()

    def test_default_plan_when_no_description(self):
        plan = self.module.build_plan("", [])
        self.assertEqual([d.key for d in plan], list(self.module.ORDER))
        # reuses the validated regex OBJECTS, never rebuilt
        for d in plan:
            self.assertIs(d.regex, self.module.KNOWN_DETECTORS[d.key])

    def test_known_four_from_description_makes_no_model_call(self):
        def explode(*a, **k):  # build_custom_regex must NOT be called for known types
            raise AssertionError("model consulted for a known category")

        original = self.module.build_custom_regex
        self.module.build_custom_regex = explode
        try:
            plan = self.module.build_plan(DESC_4, [])
        finally:
            self.module.build_custom_regex = original
        self.assertEqual([d.label for d in plan], ["手机号", "邮箱", "身份证", "APIKey"])
        self.assertEqual([d.key for d in plan], ["phone", "email", "id", "key"])

    def test_reordered_description_reorders_plan(self):
        desc = "输出格式为'邮箱,手机号,APIKey,身份证'。"
        plan = self.module.build_plan(desc, [])
        self.assertEqual([d.key for d in plan], ["email", "phone", "key", "id"])

    def test_new_type_uses_custom_factory(self):
        bank_rx = re.compile(r"(?<!\d)\d{16}(?!\d)")
        plan = self.module.build_plan(
            DESC_5_BANK, [], custom_factory=lambda label, defn: bank_rx
        )
        self.assertEqual([d.key for d in plan], ["phone", "email", "id", "key", "custom"])
        self.assertEqual(plan[4].label, "银行卡号")
        self.assertIs(plan[4].regex, bank_rx)

    def test_new_type_without_detector_degrades_to_never_match(self):
        warnings = []
        # config=None and no factory -> build_custom_regex returns None -> never-match
        plan = self.module.build_plan(DESC_5_BANK, warnings, config=None)
        self.assertEqual(len(plan), 5)
        self.assertIs(plan[4].regex, self.module._NEVER_MATCH)
        self.assertEqual(plan[4].regex.findall("6212345678901234"), [])
        self.assertTrue(any("银行卡号" in w for w in warnings))


class ScanDynamicTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.module = _load_skill_module()

    def _scan(self, archive: bytes, **extra):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "variant.zip")
            with open(path, "wb") as handle:
                handle.write(archive)
            args = {"zip_path": path, "do_ocr": False}
            args.update(extra)
            return self.module.scan(args)

    def test_public_archive_with_description_is_byte_identical(self):
        # Plumbing the description through must NOT change the known-4 counts.
        result = self.module.scan(
            {"zip_path": str(ARCHIVE), "do_ocr": False, "task_description": DESC_4}
        )
        self.assertEqual(result["breakdown"]["text"], EXPECTED_TEXT_PUBLIC)
        self.assertEqual(result["fields"], ["手机号", "邮箱", "身份证", "APIKey"])
        self.assertEqual(len(result["answer"].split(",")), 4)

    def test_variant_with_new_bank_card_type(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("a.txt", _block(phones=5, emails=3, ids=2, keys=4, banks=7))
            archive.writestr("b.log", _block(phones=1, ids=6, banks=9))

        # Inject a deterministic bank-card detector (no live model).
        original = self.module.build_custom_regex
        self.module.build_custom_regex = lambda *a, **k: re.compile(r"(?<!\d)\d{16}(?!\d)")
        try:
            result = self._scan(buffer.getvalue(), task_description=DESC_5_BANK)
        finally:
            self.module.build_custom_regex = original

        # 5 columns, in description order, with the bank column populated and the
        # KNOWN columns unchanged by the presence of 16-digit cards.
        self.assertEqual(result["fields"], ["手机号", "邮箱", "身份证", "APIKey", "银行卡号"])
        self.assertEqual(result["breakdown"]["text"], [6, 3, 8, 4, 16])  # phone,email,id,key,bank
        self.assertEqual(result["answer"], "6,3,8,4,16")
        self.assertEqual(len(result["answer"].split(",")), 5)

    def test_missing_format_line_falls_back_to_four(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("a.txt", _block(phones=2, emails=1, ids=3, keys=1, banks=5))
        result = self._scan(buffer.getvalue(), task_description="扫描并统计敏感信息。")
        # No output-format line -> default 4 columns; bank cards are ignored.
        self.assertEqual(result["fields"], ["phone", "email", "id", "key"])
        self.assertEqual(result["breakdown"]["text"], [2, 1, 3, 1])


if __name__ == "__main__":
    unittest.main()
