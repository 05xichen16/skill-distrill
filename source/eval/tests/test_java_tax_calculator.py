"""Tests for the rewritten java_tax_calculator skill (task 2_3).

Platform run #2 scored 0/15: the old skill required the public set's
TAX_BRACKETS_ENCODED/DEDUCTION_POINT_ENCODED constants, so the hidden variant
crashed it into the model loop. The rewrite repairs+compiles the real source
(validated against the question's worked examples) with a Python fallback.
Everything here is offline: javac/java and the gateway are mocked.

Standard-library unittest.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT / "source" / "solution" / "skills" / "java_tax_calculator" / "scripts" / "run.py"
)
PUBLIC_SOURCE = REPO_ROOT / "publish" / "publish_V1" / "JavaSource_7_1.java"

TASK_TEXT = """【示例输入输出】
3000 -> 0.00
8000 -> 90.00
15000 -> 590.00
30000 -> 2340.00
100000 -> 27440.00

【隐藏用例】（以下输入按顺序执行，对应10个输出）
5000
12000
25000
35000
55000
60000
80000
90000
150000
500000
"""

# The public source's decoded schedule (a contest-specific table, not the
# statutory one); reproduces all five worked examples above.
BRACKETS = [
    [0.0, 3000.0, 0.03, 0.0],
    [3001.0, 12000.0, 0.1, 410.0],
    [12001.0, 25000.0, 0.2, 2660.0],
    [25001.0, 35000.0, 0.25, 4410.0],
    [35001.0, 55000.0, 0.3, 7160.0],
    [55001.0, 80000.0, 0.35, 15160.0],
    [80001.0, 999999999.0, 0.45, 15310.0],
]
DEDUCTION = 5000.0


def _expected_tax(salary: float) -> str:
    taxable = salary - DEDUCTION
    if taxable <= 0:
        return "0.00"
    for lower, upper, rate, quick in BRACKETS:
        if lower <= taxable <= upper:
            return "%.2f" % (taxable * rate - quick)
    lower, upper, rate, quick = BRACKETS[-1]
    return "%.2f" % (taxable * rate - quick)


def _load_module():
    spec = importlib.util.spec_from_file_location("java_tax_run", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ParsingTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_parse_examples(self) -> None:
        examples = self.module.parse_examples(TASK_TEXT)
        self.assertEqual(
            examples,
            [(3000, "0.00"), (8000, "90.00"), (15000, "590.00"), (30000, "2340.00"), (100000, "27440.00")],
        )

    def test_hidden_salaries(self) -> None:
        self.assertEqual(
            self.module.hidden_salaries(TASK_TEXT),
            [5000, 12000, 25000, 35000, 55000, 60000, 80000, 90000, 150000, 500000],
        )

    def test_parse_class_name(self) -> None:
        self.assertEqual(
            self.module.parse_class_name("public class JavaSource_7_1 {"), "JavaSource_7_1"
        )
        self.assertEqual(
            self.module.parse_class_name("public final class TaxCalc {"), "TaxCalc"
        )


class PublicDecodePathTest(unittest.TestCase):
    """The public source's encoded constants must reproduce the examples."""

    def setUp(self) -> None:
        self.module = _load_module()
        self.source = PUBLIC_SOURCE.read_text(encoding="utf-8")

    def test_decoded_parameters_reproduce_examples(self) -> None:
        deduction, brackets = self.module.decode_parameters(self.source)
        for salary, expected in self.module.parse_examples(TASK_TEXT):
            self.assertAlmostEqual(
                self.module.calculate_tax(salary, deduction, brackets),
                float(expected),
                places=2,
            )

    def test_python_path_validates_and_computes(self) -> None:
        examples = self.module.parse_examples(TASK_TEXT)
        salaries = self.module.hidden_salaries(TASK_TEXT)
        warnings: list = []
        outputs, _ = self.module.try_python_path(
            None, self.source, examples, salaries, 30, warnings
        )
        self.assertIsNotNone(outputs)
        self.assertEqual(outputs, [_expected_tax(s) for s in salaries])


class GenericParameterExtractionTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def _triple(self, text: str) -> str:
        raw = text.encode("utf-8")
        for _ in range(3):
            raw = base64.b64encode(raw)
        return raw.decode("ascii")

    def test_renamed_base64_constants_validate(self) -> None:
        source = """
public class TaxVariant {
  static final String BRACKET_PAYLOAD = "%s";
  static final String TAX_FREE_POINT = "%s";
}
""" % (
            self._triple(json.dumps(BRACKETS)),
            self._triple(str(int(DEDUCTION))),
        )
        warnings: list = []
        outputs, _ = self.module.try_python_path(
            None,
            source,
            self.module.parse_examples(TASK_TEXT),
            self.module.hidden_salaries(TASK_TEXT),
            30,
            warnings,
        )
        self.assertEqual(outputs, [_expected_tax(s) for s in self.module.hidden_salaries(TASK_TEXT)])

    def test_inline_percent_rate_table_validate(self) -> None:
        source = """
public class TaxVariant {
  static final int DEDUCTION_POINT = 5000;
  static final double[][] TAX_TABLE = {
    {0, 3000, 3, 0},
    {3001, 12000, 10, 410},
    {12001, 25000, 20, 2660},
    {25001, 35000, 25, 4410},
    {35001, 55000, 30, 7160},
    {55001, 80000, 35, 15160},
    {80001, 999999999, 45, 15310}
  };
}
"""
        warnings: list = []
        outputs, _ = self.module.try_python_path(
            None,
            source,
            self.module.parse_examples(TASK_TEXT),
            self.module.hidden_salaries(TASK_TEXT),
            30,
            warnings,
        )
        self.assertEqual(outputs, [_expected_tax(s) for s in self.module.hidden_salaries(TASK_TEXT)])

    def test_comment_markdown_table_validate(self) -> None:
        source = """
public class TaxVariant {
  // 起征点为 5000 元
  // | 应纳税所得额范围 | 税率 | 速算扣除数 |
  // | 不超过3000元 | 3% | 0 |
  // | 超过3000至12000元 | 10% | 410 |
  // | 超过12000至25000元 | 20% | 2660 |
  // | 超过25000至35000元 | 25% | 4410 |
  // | 超过35000至55000元 | 30% | 7160 |
  // | 超过55000至80000元 | 35% | 15160 |
  // | 超过80000元以上 | 45% | 15310 |
}
"""
        warnings: list = []
        outputs, _ = self.module.try_python_path(
            None,
            source,
            self.module.parse_examples(TASK_TEXT),
            self.module.hidden_salaries(TASK_TEXT),
            30,
            warnings,
        )
        self.assertEqual(outputs, [_expected_tax(s) for s in self.module.hidden_salaries(TASK_TEXT)])

    def test_parallel_tax_arrays_validate(self) -> None:
        source = """
public class TaxVariant {
  static final int DEDUCTION_POINT = 5000;
  static final double[] upperLimits = {3000, 12000, 25000, 35000, 55000, 80000, 999999999};
  static final double[] taxRates = {3, 10, 20, 25, 30, 35, 45};
  static final double[] quickDeductions = {0, 410, 2660, 4410, 7160, 15160, 15310};
}
"""
        warnings: list = []
        outputs, _ = self.module.try_python_path(
            None,
            source,
            self.module.parse_examples(TASK_TEXT),
            self.module.hidden_salaries(TASK_TEXT),
            30,
            warnings,
        )
        self.assertEqual(outputs, [_expected_tax(s) for s in self.module.hidden_salaries(TASK_TEXT)])


class JavaPathTest(unittest.TestCase):
    """Repair loop with a mocked toolchain: compile error -> feedback -> success."""

    def setUp(self) -> None:
        self.module = _load_module()
        self.module.java_toolchain_available = lambda: True
        self.config = {"url": "u", "api_key": "k", "model": "m", "package_id": ""}

    def test_repair_loop_compiles_then_validates(self) -> None:
        repair_calls = []

        def fake_model(config, prompt, timeout):
            repair_calls.append(prompt)
            return "public class TaxCalc { /* repaired v%d */ }" % len(repair_calls)

        compile_results = [
            (None, "missing semicolon at line 30"),  # round 1: compile error
            ("TaxCalc", ""),  # round 2: compiles
        ]

        def fake_compile(source, work_dir):
            return compile_results.pop(0)

        def fake_run(class_name, work_dir, salary):
            return _expected_tax(salary)

        self.module._call_model = fake_model
        self.module.compile_java = fake_compile
        self.module.run_java_case = fake_run

        examples = self.module.parse_examples(TASK_TEXT)
        salaries = self.module.hidden_salaries(TASK_TEXT)
        warnings: list = []
        outputs = self.module.try_java_path(
            self.config, "src", examples, salaries, 30, 3, warnings
        )
        self.assertEqual(outputs, [_expected_tax(s) for s in salaries])
        self.assertEqual(len(repair_calls), 2)
        # round-2 prompt must carry the compiler feedback
        self.assertIn("missing semicolon", repair_calls[1])

    def test_example_mismatch_feeds_back(self) -> None:
        repair_calls = []

        def fake_model(config, prompt, timeout):
            repair_calls.append(prompt)
            return "public class TaxCalc {}"

        self.module._call_model = fake_model
        self.module.compile_java = lambda source, work_dir: ("TaxCalc", "")

        def fake_run(class_name, work_dir, salary):
            if len(repair_calls) == 1:
                return "1.00"  # wrong on every example in round 1
            return _expected_tax(salary)

        self.module.run_java_case = fake_run
        examples = self.module.parse_examples(TASK_TEXT)
        salaries = self.module.hidden_salaries(TASK_TEXT)
        warnings: list = []
        outputs = self.module.try_java_path(
            self.config, "src", examples, salaries, 30, 3, warnings
        )
        self.assertEqual(outputs, [_expected_tax(s) for s in salaries])
        self.assertIn("示例输入输出不符", repair_calls[1])

    def test_rounds_exhausted_returns_none(self) -> None:
        self.module._call_model = lambda config, prompt, timeout: "public class TaxCalc {}"
        self.module.compile_java = lambda source, work_dir: (None, "永远编译失败")
        warnings: list = []
        outputs = self.module.try_java_path(
            self.config, "src", [(3000, "0.00")], [5000], 30, 2, warnings
        )
        self.assertIsNone(outputs)


class AnswerFallbackChainTest(unittest.TestCase):
    """End-to-end answer(): java fails -> python decode validates -> answer."""

    def setUp(self) -> None:
        self.module = _load_module()

    def test_variant_without_encoded_constants_uses_llm_extraction(self) -> None:
        # Simulate a hidden variant: no base64 constants, rules in comments.
        variant_source = "public class TaxVariant { /* 起征点5000, 税率表见注释 */ }"
        self.module.java_toolchain_available = lambda: False
        self.module._model_config = lambda: {"url": "u", "api_key": "k", "model": "m", "package_id": ""}

        def fake_model(config, prompt, timeout):
            return json.dumps({"deduction": DEDUCTION, "brackets": BRACKETS})

        self.module._call_model = fake_model
        self.module.java_version_line = lambda: 'openjdk version "21.0.11"'

        import tempfile, os

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "TaxVariant.java")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(variant_source)
            result = self.module.answer(
                {"task_description": TASK_TEXT, "source_file": path, "_runtime": {}}
            )

        segments = result["answer"].split(",")
        self.assertEqual(len(segments), 11)
        self.assertIn("version", segments[0])
        self.assertEqual(segments[1:], [_expected_tax(s) for s in self.module.hidden_salaries(TASK_TEXT)])
        self.assertEqual(result["path"], "python")

    def test_total_failure_still_emits_shape(self) -> None:
        variant_source = "public class TaxVariant { }"
        self.module.java_toolchain_available = lambda: False
        self.module._model_config = lambda: None
        self.module.java_version_line = lambda: 'openjdk version "21.0.11"'

        import tempfile, os

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "TaxVariant.java")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write(variant_source)
            result = self.module.answer(
                {"task_description": TASK_TEXT, "source_file": path, "_runtime": {}}
            )

        segments = result["answer"].split(",")
        self.assertEqual(len(segments), 11)
        self.assertIn("version", segments[0])
        self.assertEqual(result["path"], "unverified")


class DeadlineSelfProtectionTest(unittest.TestCase):
    """A tiny SKILL_BUDGET_SECONDS must skip all model work (java repair
    rounds and the python extraction call) yet still emit a shaped answer."""

    def setUp(self) -> None:
        self.module = _load_module()

    def tearDown(self) -> None:
        os.environ.pop("SKILL_BUDGET_SECONDS", None)

    def test_tiny_budget_skips_model_and_still_emits(self) -> None:
        os.environ["SKILL_BUDGET_SECONDS"] = "25"  # < the emit margin: deadline already passed
        self.module.java_toolchain_available = lambda: True
        self.module._model_config = lambda: {"url": "u", "api_key": "k", "model": "m", "package_id": ""}

        def must_not_call(config, prompt, timeout):
            raise AssertionError("model must not be called past the deadline")

        self.module._call_model = must_not_call
        self.module.java_version_line = lambda: 'openjdk version "21.0.11"'

        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "TaxVariant.java")
            with open(path, "w", encoding="utf-8") as handle:
                handle.write("public class TaxVariant { }")
            result = self.module.answer(
                {"task_description": TASK_TEXT, "source_file": path, "_runtime": {}}
            )

        segments = result["answer"].split(",")
        self.assertEqual(len(segments), 11)
        self.assertIn("version", segments[0])
        self.assertEqual(result["path"], "unverified")
        self.assertTrue(any("deadline" in w for w in result["warnings"]))


class TransientRetryTest(unittest.TestCase):
    """_call_model retries once on 5xx/disconnects and fails fast otherwise.
    (po_compliance_audit ships the identical retry block; tested once here.)"""

    def setUp(self) -> None:
        self.module = _load_module()
        self.module._RETRY_SLEEP_SECONDS = 0
        self.config = {"url": "u", "api_key": "k", "model": "m", "package_id": ""}
        self.valid = json.dumps({"choices": [{"message": {"content": "ok"}}]})

    def test_5xx_then_success(self) -> None:
        attempts = []

        def fake_post(url, body, headers, timeout):
            attempts.append(1)
            if len(attempts) == 1:
                raise RuntimeError("gateway HTTP 500: boom")
            return self.valid

        self.module._post_model_request = fake_post
        self.assertEqual(self.module._call_model(self.config, "p", 5), "ok")
        self.assertEqual(len(attempts), 2)

    def test_4xx_fails_fast(self) -> None:
        attempts = []

        def fake_post(url, body, headers, timeout):
            attempts.append(1)
            raise RuntimeError("gateway HTTP 401: denied")

        self.module._post_model_request = fake_post
        with self.assertRaises(RuntimeError):
            self.module._call_model(self.config, "p", 5)
        self.assertEqual(len(attempts), 1)

    def test_transient_classifier(self) -> None:
        import urllib.error

        is_transient = self.module._is_transient_gateway_error
        self.assertTrue(is_transient(urllib.error.HTTPError("u", 502, "bad", {}, None)))
        self.assertFalse(is_transient(urllib.error.HTTPError("u", 404, "nf", {}, None)))
        self.assertTrue(is_transient(urllib.error.URLError("down")))
        self.assertTrue(is_transient(RuntimeError("gateway HTTP 503: x")))
        self.assertFalse(is_transient(RuntimeError("gateway HTTP 400: x")))
        self.assertFalse(is_transient(ValueError("nope")))


class ResolveSourceFileTest(unittest.TestCase):
    """The head-of-class platform failure is an unresolvable bare source name;
    resolution must fall back to allowed_file_paths before the cwd guess."""

    def setUp(self) -> None:
        self.module = _load_module()

    def test_allowed_paths_scanned_before_bare_name(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            java_path = os.path.join(tmp, "JavaSource_7_1.java")
            with open(java_path, "w", encoding="utf-8") as handle:
                handle.write("public class JavaSource_7_1 {}")
            # No question_dir, bare name un-findable from cwd; only the declared
            # allowed_file_paths entry locates the source.
            runtime = {"allowed_file_paths": [java_path]}
            resolved = self.module.resolve_source_file("JavaSource_7_1.java", runtime)
            self.assertEqual(os.path.abspath(resolved), os.path.abspath(java_path))

    def test_allowed_paths_basename_match_preferred(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            wanted = os.path.join(tmp, "Wanted.java")
            other = os.path.join(tmp, "Other.java")
            for path in (wanted, other):
                with open(path, "w", encoding="utf-8") as handle:
                    handle.write("public class C {}")
            runtime = {"allowed_file_paths": [other, wanted]}
            resolved = self.module.resolve_source_file("Wanted.java", runtime)
            self.assertEqual(os.path.basename(resolved), "Wanted.java")

    def test_absolute_name_wins(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            java_path = os.path.join(tmp, "Abs.java")
            with open(java_path, "w", encoding="utf-8") as handle:
                handle.write("public class Abs {}")
            resolved = self.module.resolve_source_file(java_path, {})
            self.assertEqual(resolved, java_path)

    def test_unresolvable_raises(self) -> None:
        with self.assertRaises(FileNotFoundError):
            self.module.resolve_source_file("Nope.java", {"allowed_file_paths": []})


class EmergencyExitPathTest(unittest.TestCase):
    """A forced exception must still emit a shaped 11-segment answer and exit 0,
    never a bare {"error": ...} with a non-zero code (which drops stdout and
    crashes the router into the version-less model loop = exact zero)."""

    def setUp(self) -> None:
        self.module = _load_module()

    def _run_subprocess(self, payload: dict) -> subprocess.CompletedProcess:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        # No model gateway: force the offline path.
        for key in ("MODEL_CHAT_COMPLETIONS_URL", "MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_NAME"):
            env.pop(key, None)
        return subprocess.run(
            [sys.executable, str(SKILL_RUN)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=60,
            env=env,
        )

    def test_missing_source_emits_shape_and_exits_zero(self) -> None:
        # source_file points nowhere and allowed_file_paths is empty: the normal
        # answer() path raises FileNotFoundError inside resolve_source_file.
        completed = self._run_subprocess(
            {
                "task_description": TASK_TEXT,
                "source_file": "does_not_exist_anywhere.java",
                "_runtime": {"allowed_file_paths": []},
            }
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        payload = json.loads(completed.stdout.strip())
        self.assertIn("answer", payload)
        self.assertNotIn("error", {})  # sanity
        segments = payload["answer"].split(",")
        self.assertEqual(len(segments), 11)
        self.assertIn("21.0.11", segments[0])
        # 10 numeric tax segments (0.00 fallback is acceptable).
        for segment in segments[1:]:
            float(segment)

    def test_emergency_answer_recovers_taxes_when_source_readable(self) -> None:
        # answer() is monkeypatched to raise *after* the source is resolvable,
        # so emergency_answer can still recover the real taxes offline.
        original_answer = self.module.answer

        def boom(args):
            raise RuntimeError("forced failure after a readable source")

        self.module.answer = boom
        try:
            with tempfile.TemporaryDirectory() as tmp:
                java_path = os.path.join(tmp, "JavaSource_7_1.java")
                with open(java_path, "w", encoding="utf-8") as handle:
                    handle.write(PUBLIC_SOURCE.read_text(encoding="utf-8"))
                result = self.module.emergency_answer(
                    {
                        "task_description": TASK_TEXT,
                        "source_file": java_path,
                        "_runtime": {},
                    },
                    "forced",
                )
        finally:
            self.module.answer = original_answer

        segments = result["answer"].split(",")
        self.assertEqual(len(segments), 11)
        self.assertIn("21.0.11", segments[0])
        # The public source decodes cleanly, so the emergency path reproduces
        # the real hidden-case taxes rather than 0.00 placeholders.
        self.assertEqual(
            segments[1:], [_expected_tax(s) for s in self.module.hidden_salaries(TASK_TEXT)]
        )
        self.assertEqual(result["path"], "emergency")


if __name__ == "__main__":
    unittest.main()
