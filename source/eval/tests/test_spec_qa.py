"""Offline tests for the spec_qa skill.

Fully offline: the model gateway is replaced by an injected fake answerer, so
nothing touches the network. Covers the behaviours the grader depends on:

- dynamic question parsing (N == 10, N != 10, shuffled, interleaved groups);
- group -> spec-file routing, plus the all-specs fallback when routing fails;
- keyword retrieval pulls the window that contains the answer from a fixture;
- ``;`` joining yields exactly N segments, in Q order, with answer-internal
  semicolons neutralised so the segment count never drifts;
- a failing question -> placeholder with no dropped or misindexed segment;
- ``.docx``-only degradation extracts text from a minimal zip.

Standard-library unittest. The Chinese literals in the fixtures and assertions
are real spec wording; this test module is allowed non-ASCII because it is not a
skill entrypoint (the skill source stays pure-ASCII).
"""
from __future__ import annotations

import importlib.util
import io
import os
import tempfile
import unittest
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT
    / "source"
    / "solution"
    / "skills"
    / "spec_qa"
    / "scripts"
    / "run.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("spec_qa_run", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = _load_module()


# Real spec file names (so routing keyword matching is exercised as in prod).
JAVA_MD = "华为Java语言编程规范V5.x.md"
PYTHON_MD = "华为Python语言编程规范V3.x.md"
CPP_MD = "华为C++语言编程规范V5.x.md"
JSTS_MD = "华为JavaScript&TypeScript语言编程规范V3.x.md"
WEB_MD = "华为Web应用安全开发规范.md"

LB = chr(0x3010)
RB = chr(0x3011)


def _group(label: str) -> str:
    return LB + label + RB


# A realistic 10-question task description, mirroring the public q_1_2.
TASK_10 = "\n".join(
    [
        "附件是华为编程规范集：请根据各规范回答以下问题：",
        "",
        _group("Java规范"),
        "Q1: Java源文件的import排序中，华为公司包应该在哪一类之后？",
        "Q2: What suffix should be used for long type numeric literals in Java?",
        "",
        _group("Python规范"),
        "Q3: Python中导入模块应该按照什么顺序排列？",
        "Q4: In Python, which operator should be used when comparing with None?",
        "",
        _group("C++规范"),
        "Q5: C++源文件和头文件的扩展名分别是什么？",
        "Q6: In C++, copy constructor and copy assignment operator together or separately?",
        "",
        _group("JS/TS规范"),
        "Q7: JavaScript/TypeScript中构造器函数和类应该采用什么命名风格？",
        "Q8: In JS/TS, which operators should be used for equality comparison?",
        "",
        _group("Web安全规范"),
        "Q9: Web应用中口令输入框的type属性应该设置为什么值？",
        "Q10: In Web applications, what attribute should session cookies have?",
    ]
)


def _force_offline_env() -> None:
    for key in ("MODEL_CHAT_COMPLETIONS_URL", "MODEL_BASE_URL", "MODEL_API_KEY",
                "MODEL_NAME", "PACKAGE_ID", "packageId"):
        os.environ.pop(key, None)


def _fake_answerer(by_question: Dict[str, str], default: str = "") -> Callable[..., str]:
    """A model stub that keys on which question the prompt is for.

    The per-question prompt starts with ``Question: <text>``; we map each known
    question's text fragment to a canned answer. A value that is an Exception is
    raised to exercise the retry/fallback path.
    """

    def answerer(config: Dict[str, str], prompt: str, timeout: int) -> str:
        for fragment, value in by_question.items():
            if fragment in prompt:
                if isinstance(value, Exception):
                    raise value
                return value
        return default

    return answerer


def _set_fake_config() -> None:
    os.environ["MODEL_CHAT_COMPLETIONS_URL"] = "http://example.invalid/v1/chat/completions"
    os.environ["MODEL_API_KEY"] = "sk-test"
    os.environ["MODEL_NAME"] = "test-model"


# --- question parsing ------------------------------------------------------

class ParseQuestionsTest(unittest.TestCase):
    def test_parses_ten_questions_in_order_with_groups(self) -> None:
        items = MOD.parse_questions(TASK_10)
        self.assertEqual(len(items), 10)
        self.assertEqual([it["q"] for it in items], ["Q%d" % i for i in range(1, 11)])
        # Group headers are attached to the questions under them.
        self.assertIn("Java", items[0]["group"])
        self.assertIn("Python", items[2]["group"])
        self.assertIn("C++", items[4]["group"])
        self.assertIn("JS", items[6]["group"])
        self.assertIn("Web", items[8]["group"])

    def test_variable_count_not_hardcoded_to_ten(self) -> None:
        text = "\n".join([
            _group("Java规范"),
            "Q1: first?",
            "Q2: second?",
            "Q3: third?",
        ])
        items = MOD.parse_questions(text)
        self.assertEqual(len(items), 3)
        self.assertEqual([it["num"] for it in items], [1, 2, 3])

    def test_shuffled_questions_sorted_by_number(self) -> None:
        text = "\n".join([
            "Q3: third?",
            "Q1: first?",
            "Q2: second?",
        ])
        items = MOD.parse_questions(text)
        self.assertEqual([it["num"] for it in items], [1, 2, 3])
        self.assertTrue(items[0]["text"].startswith("first"))

    def test_interleaved_groups_track_nearest_header(self) -> None:
        text = "\n".join([
            _group("Python规范"),
            "Q1: py one?",
            _group("Java规范"),
            "Q2: java two?",
            _group("Python规范"),
            "Q3: py three?",
        ])
        items = MOD.parse_questions(text)
        self.assertIn("Python", items[0]["group"])
        self.assertIn("Java", items[1]["group"])
        self.assertIn("Python", items[2]["group"])

    def test_question_punctuation_variants(self) -> None:
        # "Q1." and a full-width colon both parse.
        text = "Q1. alpha?\nQ2： beta?"
        items = MOD.parse_questions(text)
        self.assertEqual(len(items), 2)
        self.assertTrue(items[1]["text"].startswith("beta"))

    def test_return_format_example_block_excluded(self) -> None:
        # The trailing "return format example" block lists a template like
        # "Q1ans;Q2ans;..." which must NOT inflate the question count.
        text = "\n".join([
            _group("Java规范"),
            "Q1: first?",
            "Q2: second?",
            "重要提示：答案用英文分号分隔，按Q1~Q2顺序返回。",
            _group("返回格式示例"),
            "Q1答案;Q2答案",
        ])
        items = MOD.parse_questions(text)
        self.assertEqual(len(items), 2)  # exactly the two real questions
        self.assertEqual([it["num"] for it in items], [1, 2])

    def test_duplicate_number_keeps_first(self) -> None:
        text = "Q1: real one?\nQ1: stray duplicate?\nQ2: two?"
        items = MOD.parse_questions(text)
        self.assertEqual(len(items), 2)
        self.assertTrue(items[0]["text"].startswith("real one"))


# --- routing ---------------------------------------------------------------

class RoutingTest(unittest.TestCase):
    SPEC_NAMES = [JAVA_MD, PYTHON_MD, CPP_MD, JSTS_MD, WEB_MD]

    def test_each_group_routes_to_correct_file(self) -> None:
        cases = [
            ("Java规范", JAVA_MD),
            ("Python规范", PYTHON_MD),
            ("C++规范", CPP_MD),
            ("JS/TS规范", JSTS_MD),
            ("Web安全规范", WEB_MD),
        ]
        for group, expected in cases:
            got = MOD.route_spec(group, "", self.SPEC_NAMES)
            self.assertEqual(got, expected, "group %r -> %r" % (group, got))

    def test_javascript_group_not_stolen_by_java(self) -> None:
        # "JS/TS" must route to the JavaScript file, never the Java file.
        got = MOD.route_spec("JS/TS规范", "", self.SPEC_NAMES)
        self.assertEqual(got, JSTS_MD)

    def test_no_group_falls_back_to_none_for_all_specs(self) -> None:
        # A question with no routable group/text returns None -> the caller then
        # retrieves across all specs (exercised in EndToEndTest).
        got = MOD.route_spec("", "some unrelated free text", self.SPEC_NAMES)
        self.assertIsNone(got)

    def test_routes_from_question_text_when_group_empty(self) -> None:
        got = MOD.route_spec("", "In Python, comparing with None?", self.SPEC_NAMES)
        self.assertEqual(got, PYTHON_MD)


# --- retrieval -------------------------------------------------------------

class RetrievalTest(unittest.TestCase):
    def test_retrieves_window_containing_answer(self) -> None:
        # Small fixture with the real Python answer line buried in filler.
        answer_line = (
            "#### G.FMT.07 导入部分(imports)应该按照"
            "标准库、第三方库、应用程序"
            "自定义模块的顺序排列导入"
        )
        lines = ["filler line %d" % i for i in range(60)]
        lines[30] = answer_line
        spec_text = "\n".join(lines)
        question = (
            "Python中导入模块应该按照什么"
            "顺序排列？"
        )
        snippet = MOD.retrieve(spec_text, question, max_chars=2000, window_lines=10)
        self.assertIn("G.FMT.07", snippet)
        self.assertIn("标准库", snippet)  # the answer keyword
        self.assertLessEqual(len(snippet), 2000)

    def test_respects_char_cap(self) -> None:
        spec_text = "\n".join("keyword line %d" % i for i in range(500))
        snippet = MOD.retrieve(spec_text, "keyword", max_chars=300, window_lines=20)
        self.assertLessEqual(len(snippet), 300 + 5)  # +sep slack

    def test_no_keyword_match_returns_head(self) -> None:
        spec_text = "\n".join("alpha %d" % i for i in range(100))
        snippet = MOD.retrieve(spec_text, "zzzzz", max_chars=120, window_lines=5)
        self.assertLessEqual(len(snippet), 120)
        self.assertTrue(snippet.startswith("alpha 0"))


# --- answer cleaning + semicolon safety ------------------------------------

class CleanAnswerTest(unittest.TestCase):
    def test_strips_label_and_quotes(self) -> None:
        self.assertEqual(MOD.clean_answer('Q3: "hello world"'), "hello world")
        self.assertEqual(MOD.clean_answer("Answer: foo"), "foo")

    def test_first_line_only(self) -> None:
        self.assertEqual(MOD.clean_answer("the answer\n\nextra junk"), "the answer")

    def test_internal_semicolon_neutralised(self) -> None:
        # A semicolon inside an answer would forge an extra segment.
        cleaned = MOD.clean_answer("a; b; c")
        self.assertNotIn(";", cleaned)
        self.assertEqual(cleaned, "a, b, c")

    def test_empty_stays_empty(self) -> None:
        self.assertEqual(MOD.clean_answer("   "), "")


# --- end-to-end joining + fallback -----------------------------------------

def _make_specs(tmp: Path) -> Path:
    """Write tiny but answer-bearing spec .md fixtures into a folder."""
    spec_dir = tmp / "spec"
    spec_dir.mkdir()
    fixtures = {
        JAVA_MD: (
            "import section\n"
            "Java import: 华为公司包 com.huawei 放在"
            "第三方库之后\n"
            "long literal uses L suffix\n"
        ),
        PYTHON_MD: (
            "imports\n"
            "G.FMT.07 标准库、第三方库、"
            "应用程序自定义模块\n"
            "use is / is not for None\n"
        ),
        CPP_MD: "files use cpp and h extensions\ncopy ctor declared 同时\n",
        JSTS_MD: "constructor and class use 大驼峰 naming\nuse === and !==\n",
        WEB_MD: (
            "password input type=password\n"
            "session cookie HttpOnly prevents XSS\n"
        ),
    }
    for name, text in fixtures.items():
        (spec_dir / name).write_bytes(text.encode("utf-8"))
    return spec_dir


class EndToEndTest(unittest.TestCase):
    def setUp(self) -> None:
        _force_offline_env()

    def test_ten_segments_in_order_semicolon_joined(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = _make_specs(Path(tmp))
            # Map each question fragment to a canned (spec-original) answer;
            # Q5's answer deliberately carries a ';' to prove neutralisation.
            answers = {
                "import排序": "第三方库之后",          # Q1
                "long type numeric": "L",                                            # Q2
                "导入模块": "标准库、第三方库、应用程序自定义模块",  # Q3
                "comparing with None": "is / is not",                                # Q4
                "扩展名": "cpp; h",   # Q5 -> ';' must be neutralised
                "together or separately": "同时",                            # Q6
                "命名风格": "大驼峰",                     # Q7
                "equality comparison": "=== 和 !==",                             # Q8
                "type属性": "password",                                      # Q9
                "session cookies": "HttpOnly",                                       # Q10
            }
            args = {
                "task_description": TASK_10,
                "spec_dir": str(spec_dir),
                "_runtime": {"question_dir": str(spec_dir.parent), "question_id": "1_2"},
            }
            _set_fake_config()
            try:
                result = MOD.answer(args, answerer=_fake_answerer(answers))
            finally:
                _force_offline_env()

            self.assertEqual(result["n"], 10)
            segments = result["answer"].split(";")
            self.assertEqual(len(segments), 10)  # exactly N segments
            # Q5's internal ';' did not forge an extra segment.
            self.assertEqual(segments[4], "cpp, h")
            # Order is preserved Q1..Q10.
            self.assertEqual(segments[0], "第三方库之后")
            self.assertEqual(segments[1], "L")
            self.assertEqual(segments[9], "HttpOnly")
            # per_question records the routed source file.
            self.assertEqual(result["per_question"][0]["source"], JAVA_MD)
            self.assertEqual(result["per_question"][2]["source"], PYTHON_MD)

    def test_grader_scores_full_with_real_rubric(self) -> None:
        # Feed the joined answer through the real match1 grader and assert a
        # perfect score against the public rubric -> proves the segments line up.
        import importlib.util as _ilu

        score_path = REPO_ROOT / "source" / "eval" / "score.py"
        spec = _ilu.spec_from_file_location("score_mod", score_path)
        assert spec and spec.loader
        score_mod = _ilu.module_from_spec(spec)
        spec.loader.exec_module(score_mod)

        rubric = ";".join([
            "or[安卓,android,Android]",
            "and[L]",
            "and[标准库,第三方库,应用程序自定义模块]",
            "or[is,is not]",
            "and[cpp,h]",
            "and[同时]",
            "and[大驼峰]",
            "and[===,!==]",
            "and[password]",
            "and[HttpOnly]",
        ])
        answer = ";".join([
            "com.huawei 放在第三方库之后，即 android 之后",
            "L",
            "标准库、第三方库、应用程序自定义模块",
            "is / is not",
            "cpp, h",
            "同时声明",
            "大驼峰命名",
            "=== 和 !==",
            "password",
            "HttpOnly",
        ])
        earned, detail = score_mod.score_match(rubric, answer, 2.0, ";")
        self.assertAlmostEqual(earned, 2.0, places=6)
        self.assertEqual(detail, "10/10 segments")

    def test_failed_question_gets_placeholder_no_drop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = _make_specs(Path(tmp))
            # Q2 always raises; every other question answers fine.
            answers = {
                "import排序": "a1",
                "long type numeric": RuntimeError("gateway down"),  # Q2 fails
                "导入模块": "a3",
                "comparing with None": "a4",
                "扩展名": "a5",
                "together or separately": "a6",
                "命名风格": "a7",
                "equality comparison": "a8",
                "type属性": "a9",
                "session cookies": "a10",
            }
            args = {
                "task_description": TASK_10,
                "spec_dir": str(spec_dir),
                "_runtime": {"question_dir": str(spec_dir.parent), "question_id": "1_2"},
            }
            _set_fake_config()
            os.environ["SPEC_QA_RETRIES"] = "2"
            try:
                result = MOD.answer(args, answerer=_fake_answerer(answers))
            finally:
                _force_offline_env()
                os.environ.pop("SPEC_QA_RETRIES", None)

            segments = result["answer"].split(";")
            self.assertEqual(len(segments), 10)  # still exactly N
            # Position 1 (Q2) is a non-empty placeholder, not dropped/blank.
            self.assertTrue(segments[1].strip())
            self.assertNotIn(";", segments[1])
            # Neighbours kept their real answers (positions intact).
            self.assertEqual(segments[0], "a1")
            self.assertEqual(segments[2], "a3")
            self.assertTrue(any("Q2" in w for w in result["warnings"]))

    def test_no_config_all_placeholders_no_crash(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = _make_specs(Path(tmp))
            args = {
                "task_description": TASK_10,
                "spec_dir": str(spec_dir),
                "_runtime": {"question_dir": str(spec_dir.parent), "question_id": "1_2"},
            }
            # No MODEL_* env -> config is None.
            result = MOD.answer(args)
            self.assertEqual(result["n"], 10)
            self.assertEqual(len(result["answer"].split(";")), 10)
            self.assertTrue(any("not configured" in w for w in result["warnings"]))

    def test_all_specs_fallback_when_no_group(self) -> None:
        # A question with no group header still gets answered (routes to ALL).
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = _make_specs(Path(tmp))
            task = "Q1: some free-floating question with no group?"
            args = {
                "task_description": task,
                "spec_dir": str(spec_dir),
                "_runtime": {"question_dir": str(spec_dir.parent), "question_id": "1_2"},
            }
            _set_fake_config()
            try:
                result = MOD.answer(args, answerer=_fake_answerer({"free-floating": "ok"}))
            finally:
                _force_offline_env()
            self.assertEqual(result["n"], 1)
            self.assertEqual(result["answer"], "ok")
            self.assertEqual(result["per_question"][0]["source"], "ALL")


# --- docx degradation ------------------------------------------------------

class DocxDegradationTest(unittest.TestCase):
    def test_extracts_text_from_minimal_docx(self) -> None:
        # Build a minimal docx (zip with word/document.xml) carrying one run.
        buffer = io.BytesIO()
        document_xml = (
            '<?xml version="1.0"?>'
            "<w:document><w:body>"
            "<w:p><w:r><w:t>hello </w:t></w:r><w:r><w:t>world</w:t></w:r></w:p>"
            "<w:p><w:r><w:t>second &amp; line</w:t></w:r></w:p>"
            "</w:body></w:document>"
        )
        with zipfile.ZipFile(buffer, "w") as archive:
            archive.writestr("word/document.xml", document_xml)
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "only.docx")
            with open(path, "wb") as handle:
                handle.write(buffer.getvalue())
            text = MOD._read_docx_text(path)
        self.assertIn("hello world", text)
        self.assertIn("second & line", text)  # entity decoded

    def test_load_specs_uses_docx_only_when_no_md(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "spec"
            spec_dir.mkdir()
            # One .md spec and one docx-only spec.
            (spec_dir / "alpha.md").write_bytes("alpha body".encode("utf-8"))
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    "<w:document><w:body><w:p><w:r><w:t>beta body</w:t>"
                    "</w:r></w:p></w:body></w:document>",
                )
            (spec_dir / "beta.docx").write_bytes(buffer.getvalue())
            specs = MOD.load_specs(str(spec_dir))
            self.assertIn("alpha.md", specs)
            self.assertIn("beta.docx", specs)
            self.assertIn("beta body", specs["beta.docx"])

    def test_load_specs_prefers_md_over_sibling_docx(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            spec_dir = Path(tmp) / "spec"
            spec_dir.mkdir()
            (spec_dir / "doc.md").write_bytes("the markdown body".encode("utf-8"))
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, "w") as archive:
                archive.writestr(
                    "word/document.xml",
                    "<w:document><w:body><w:p><w:r><w:t>docx body</w:t>"
                    "</w:r></w:p></w:body></w:document>",
                )
            (spec_dir / "doc.docx").write_bytes(buffer.getvalue())
            specs = MOD.load_specs(str(spec_dir))
            # Only the .md sibling is loaded; the docx is skipped.
            self.assertIn("doc.md", specs)
            self.assertNotIn("doc.docx", specs)


if __name__ == "__main__":
    unittest.main()
