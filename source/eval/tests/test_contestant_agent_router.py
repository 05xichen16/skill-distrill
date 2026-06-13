"""Offline tests for ContestantAgent's explicit skill router.

The router is deliberately small and high-confidence: when a public contest
task clearly maps to an executable skill, the agent calls ``skill_run`` directly
and returns that skill's ``answer`` field. These tests keep that integration
stable without touching the model gateway.
"""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from source.solution.contestant_agent import ContestantAgent


ALL_ROUTED_SKILLS = [
    "interface_test",
    "wiki_dialog",
    "prompt_learn_classify",
    "sensitive_scan",
    "spec_qa",
    "date_normalize",
    "system_issue_locator",
    "java_tax_calculator",
    "purchase_clean_summary",
    "po_compliance_audit",
]


class _StubContext:
    def __init__(self, skills=None, answer="ROUTED", allowed_file_paths=None, question_dir=".") -> None:
        self.available_skills = [{"name": name} for name in (skills or ALL_ROUTED_SKILLS)]
        self.calls = []
        self.answer = answer
        self.allowed_file_paths = [Path(p) for p in (allowed_file_paths or [])]
        self.question_dir = Path(question_dir)

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return '{"answer": "%s"}' % self.answer


class ContestantAgentRouterTest(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.agent = ContestantAgent()
        self._old_use_llm = os.environ.get("AGENT_DEMO_USE_LLM")

    def tearDown(self) -> None:
        if self._old_use_llm is None:
            os.environ.pop("AGENT_DEMO_USE_LLM", None)
        else:
            os.environ["AGENT_DEMO_USE_LLM"] = self._old_use_llm

    def test_spec_qa_route(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "华为编程规范问答",
                "question": "Q1: ...",
                "files": ["./编程规范/"],
            },
            context=_StubContext(),
        )
        self.assertEqual(route, ("spec_qa", {"task_description": "Q1: ...", "spec_dir": "./编程规范"}))

    def test_interface_route_uses_common_parent(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "接口测试结果识别",
                "question": "run cases",
                "files": [
                    "./测试用例接口文档/api_doc.md",
                    "./测试用例接口文档/test_cases.json",
                    "./测试用例接口文档/auth_config.json",
                ],
            },
            context=_StubContext(),
        )
        self.assertEqual(
            route,
            (
                "interface_test",
                {
                    "task_description": "run cases",
                    "doc_dir": "./测试用例接口文档",
                },
            ),
        )

    def test_wiki_dialog_route_uses_common_parent(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "IDE 插件 FSE 数字人问答",
                "question": "answer dialogs",
                "files": [
                    "./IDE插件FSE/persona.md",
                    "./IDE插件FSE/chat_history.db",
                    "./IDE插件FSE/source_access.json",
                    "./IDE插件FSE/dialog_tests_complex.json",
                ],
            },
            context=_StubContext(),
        )
        self.assertEqual(route[0], "wiki_dialog")
        self.assertEqual(route[1]["source_dir"], "./IDE插件FSE")

    def test_prompt_learn_route_finds_train_and_validation_dirs(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "提示词学习与推理",
                "question": "classify images",
                "files": ["./训练集/", "./验证集/"],
            },
            context=_StubContext(),
        )
        self.assertEqual(route[0], "prompt_learn_classify")
        self.assertEqual(route[1]["train_dir"], "./训练集")
        self.assertEqual(route[1]["val_dir"], "./验证集")

    def test_sensitive_scan_route_uses_zip_path(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "敏感信息扫描",
                "question": "scan archive",
                "files": ["sensitive_data_2_1.zip"],
            },
            context=_StubContext(),
        )
        self.assertEqual(route[0], "sensitive_scan")
        self.assertEqual(route[1]["zip_path"], "sensitive_data_2_1.zip")
        # The description is plumbed so the skill can read the (possibly extended)
        # category list + output order at runtime.
        self.assertIn("task_description", route[1])
        self.assertIsInstance(route[1]["task_description"], str)

    def test_date_normalize_route_uses_text_file(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "客服消息日期提取与标准化",
                "question": "parse dates",
                "files": ["customer_date_messages.txt"],
            },
            context=_StubContext(),
        )
        self.assertEqual(route, ("date_normalize", {"message_file": "customer_date_messages.txt"}))

    def test_system_issue_route_uses_common_parent(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "系统问题定位与根因判断",
                "question": "locate issue",
                "files": [
                    "./系统问题定位/frontend_log.log",
                    "./系统问题定位/backend_validation.log",
                    "./系统问题定位/network.har",
                    "./系统问题定位/form_schema.json",
                ],
            },
            context=_StubContext(),
        )
        self.assertEqual(route[0], "system_issue_locator")
        self.assertEqual(route[1]["source_dir"], "./系统问题定位")

    def test_java_tax_route_uses_source_file(self) -> None:
        # No allowed_file_paths to resolve against: the bare declared name is
        # passed through unchanged (the skill still has its own fallbacks).
        route = self.agent._explicit_skill_route(
            question={
                "title": "Java个人所得税计算器",
                "question": "hidden cases",
                "files": ["JavaSource_7_1.java"],
            },
            context=_StubContext(),
        )
        self.assertEqual(
            route,
            (
                "java_tax_calculator",
                {"task_description": "hidden cases", "source_file": "JavaSource_7_1.java"},
            ),
        )

    def test_java_tax_route_resolves_absolute_source_file(self) -> None:
        # When the bare declared name maps to an absolute allowed_file_paths
        # entry, the route passes the absolute path so the skill subprocess
        # (cwd = skill dir) can find it instead of crashing into the model loop.
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            abs_java = os.path.join(tmp, "JavaSource_7_1.java")
            with open(abs_java, "w", encoding="utf-8") as handle:
                handle.write("public class JavaSource_7_1 {}")
            route = self.agent._explicit_skill_route(
                question={
                    "title": "Java个人所得税计算器",
                    "question": "hidden cases",
                    "files": ["JavaSource_7_1.java"],
                },
                context=_StubContext(allowed_file_paths=[abs_java]),
            )
            self.assertEqual(route[0], "java_tax_calculator")
            self.assertEqual(os.path.abspath(route[1]["source_file"]), os.path.abspath(abs_java))

    def test_purchase_clean_route_uses_source_dir(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "采购数据清洗与汇总",
                "question": "clean purchase data",
                "files": ["./采购数据清洗与汇总/"],
            },
            context=_StubContext(),
        )
        # task_description carries the cleaning rules for the LLM rescue pass.
        self.assertEqual(
            route,
            (
                "purchase_clean_summary",
                {"task_description": "clean purchase data", "source_dir": "./采购数据清洗与汇总"},
            ),
        )

    def test_po_audit_route_uses_source_dir(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "采购PO合规审计",
                "question": "audit POs",
                "files": ["./采购PO合规审计/"],
            },
            context=_StubContext(),
        )
        # task_description rides along so the skill can parse the variant's
        # amount threshold out of the question text.
        self.assertEqual(
            route,
            (
                "po_compliance_audit",
                {"task_description": "audit POs", "source_dir": "./采购PO合规审计"},
            ),
        )

    async def test_solve_returns_skill_answer_even_when_main_llm_disabled(self) -> None:
        os.environ["AGENT_DEMO_USE_LLM"] = "false"
        context = _StubContext(answer="TC009,TC011")
        answer = await self.agent.solve(
            question={
                "title": "接口测试结果识别",
                "question": "run cases",
                "files": [
                    "./测试用例接口文档/api_doc.md",
                    "./测试用例接口文档/test_cases.json",
                    "./测试用例接口文档/auth_config.json",
                ],
            },
            context=context,
        )
        self.assertEqual(answer, "TC009,TC011")
        self.assertEqual(context.calls[0][0], "skill_run")
        self.assertEqual(context.calls[0][1]["name"], "interface_test")

    def test_missing_skill_does_not_route(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "敏感信息扫描",
                "question": "scan archive",
                "files": ["sensitive_data_2_1.zip"],
            },
            context=_StubContext(skills=["spec_qa"]),
        )
        self.assertIsNone(route)

    _PUBLIC_HIDDEN_TAXES = [
        "0.00", "290.00", "1340.00", "3090.00", "7840.00", "9340.00",
        "11090.00", "22940.00", "49940.00", "207440.00",
    ]

    @property
    def _public_source(self) -> Path:
        return (
            Path(__file__).resolve().parents[3]
            / "publish" / "publish_V1" / "JavaSource_7_1.java"
        )

    _TASK_TEXT = (
        "隐藏用例\n5000\n12000\n25000\n35000\n55000\n60000\n80000\n90000\n150000\n500000"
    )

    async def test_java_tax_solved_in_process_before_any_skill_call(self) -> None:
        """The Java tax answer is computed deterministically IN-PROCESS as the
        primary path: even a skill whose ``skill_run`` would crash is never
        reached, so the exact-zero model-loop path can never claim this question.
        """
        # Model loop disabled, so a correct answer PROVES it came from the
        # deterministic in-process computation, not the model.
        os.environ["AGENT_DEMO_USE_LLM"] = "false"

        class _DyingContext(_StubContext):
            async def call_tool(self, name, args):
                self.calls.append((name, args))
                raise RuntimeError("skill subprocess killed (timeout)")

        context = _DyingContext(allowed_file_paths=[str(self._public_source)])
        answer = await self.agent.solve(
            question={
                "title": "Java个人所得税计算器",
                "question": self._TASK_TEXT,
                "files": [str(self._public_source)],
            },
            context=context,
        )
        # In-process leads: the (dying) skill subprocess is never even invoked.
        self.assertEqual(context.calls, [])
        segments = answer.split(",")
        self.assertEqual(len(segments), 11)
        self.assertIn("21.0.11", segments[0])
        self.assertEqual(segments[1:], self._PUBLIC_HIDDEN_TAXES)

    async def test_java_tax_solved_even_when_skill_not_discovered(self) -> None:
        """The exact-zero failure mode: the skill is NOT in available_skills, so
        the explicit route never fires. solve() must still answer correctly from
        the in-process path instead of surrendering to the version-less model
        loop (which would score 0 on the match2 grader).
        """
        os.environ["AGENT_DEMO_USE_LLM"] = "false"
        # available_skills deliberately omits java_tax_calculator.
        context = _StubContext(
            skills=["spec_qa", "sensitive_scan"],
            allowed_file_paths=[str(self._public_source)],
        )
        answer = await self.agent.solve(
            question={
                "title": "Java个人所得税计算器",
                "question": self._TASK_TEXT,
                "files": [str(self._public_source)],
            },
            context=context,
        )
        self.assertEqual(context.calls, [])  # no skill route possible, none attempted
        segments = answer.split(",")
        self.assertEqual(len(segments), 11)
        self.assertIn("21.0.11", segments[0])
        self.assertEqual(segments[1:], self._PUBLIC_HIDDEN_TAXES)

    # --- purchase_clean_summary (2_1) in-process floor ----------------------
    # The skill's 900s subprocess can be killed / lose stdout under concurrent
    # gateway load (the sibling interface_test line in the platform log timed out
    # at 600s the same way), or the shared run-cap can fire mid-OCR. That used to
    # drop 2_1 to the version-less model loop — an exact zero on this
    # query-ordered positional grader. solve() must instead emit the
    # deterministic NO-OCR baseline in-process: 10/12 on the public set, instant,
    # and impossible to kill mid-call.

    @property
    def _public_purchase_dir(self) -> Path:
        return (
            Path(__file__).resolve().parents[3]
            / "publish" / "publish_V1" / "采购数据清洗与汇总"
        )

    def _purchase_no_ocr_baseline(self) -> str:
        """The deterministic answer solve()'s floor must reproduce (do_ocr off,
        no LLM rescue — config is None offline). Computed live so the assertion
        tracks the algorithm instead of a brittle hard-coded string."""
        from source.solution.skills.purchase_clean_summary.scripts import run as R

        rules = R.read_text(str(self._public_purchase_dir / "data_rules.md"))
        out = R.answer(
            {
                "source_dir": str(self._public_purchase_dir),
                "task_description": rules,
                "do_ocr": False,
            }
        )
        return out["answer"]

    async def test_purchase_floor_answers_when_subprocess_dies(self) -> None:
        """The observed risk: the purchase skill subprocess is killed (timeout /
        dropped stdout). The full-OCR skill path still gets first crack, but when
        it dies the in-process no-OCR floor answers instead of the model loop."""
        if not self._public_purchase_dir.is_dir():
            self.skipTest("public dataset not present")
        # Model loop disabled, so a correct answer PROVES it came from the
        # deterministic in-process floor, not the model.
        os.environ["AGENT_DEMO_USE_LLM"] = "false"
        expected = self._purchase_no_ocr_baseline()

        class _DyingContext(_StubContext):
            async def call_tool(self, name, args):
                self.calls.append((name, args))
                raise RuntimeError("skill subprocess killed (timeout 900s)")

        context = _DyingContext(allowed_file_paths=[str(self._public_purchase_dir)])
        answer = await self.agent.solve(
            question={
                "title": "采购数据清洗与汇总",
                "question": "clean purchase data",
                "files": [str(self._public_purchase_dir)],
            },
            context=context,
        )
        # The skill WAS attempted first (full-OCR path); only after it died did
        # the floor take over.
        self.assertEqual(context.calls[0][0], "skill_run")
        self.assertEqual(context.calls[0][1]["name"], "purchase_clean_summary")
        self.assertEqual(answer, expected)
        segments = answer.split(",")
        self.assertTrue(segments and all(s.lstrip("-").isdigit() for s in segments))
        # A real computation, not the right-length all-zero emergency floor.
        self.assertTrue(any(s not in ("0", "-0") for s in segments))

    async def test_purchase_floor_answers_when_skill_not_discovered(self) -> None:
        """The skill-absent exact-zero mode: purchase_clean_summary is not in
        available_skills, so the explicit route never fires. The content-gated
        floor must still answer instead of surrendering to the model loop."""
        if not self._public_purchase_dir.is_dir():
            self.skipTest("public dataset not present")
        os.environ["AGENT_DEMO_USE_LLM"] = "false"
        expected = self._purchase_no_ocr_baseline()
        # available_skills deliberately omits purchase_clean_summary.
        context = _StubContext(
            skills=["spec_qa", "sensitive_scan"],
            allowed_file_paths=[str(self._public_purchase_dir)],
        )
        answer = await self.agent.solve(
            question={
                "title": "采购数据清洗与汇总",
                "question": "clean purchase data",
                "files": [str(self._public_purchase_dir)],
            },
            context=context,
        )
        self.assertEqual(context.calls, [])  # no purchase route possible, none attempted
        self.assertEqual(answer, expected)


class JavaTaxSalaryExtractionTest(unittest.IsolatedAsyncioTestCase):
    """2_3: the model extracts ONLY the input salaries (strict JSON int array);
    the deterministic formula consumes them. A malformed/disabled/failed
    extraction must transparently return None so the skill parses them
    deterministically -- the model can never poison the positional tax segments
    or block the in-process answer."""

    def setUp(self) -> None:
        self.agent = ContestantAgent()

    # --- _parse_salary_list: strict contract -------------------------------
    def test_parse_plain_array(self) -> None:
        self.assertEqual(self.agent._parse_salary_list("[5000, 12000, 25000]"), [5000, 12000, 25000])

    def test_parse_array_in_prose(self) -> None:
        self.assertEqual(self.agent._parse_salary_list("结果：[5000,12000] 完成"), [5000, 12000])

    def test_parse_strips_think_tags(self) -> None:
        self.assertEqual(self.agent._parse_salary_list("<think>算一下</think>[800,900]"), [800, 900])

    def test_parse_accepts_integral_floats(self) -> None:
        self.assertEqual(self.agent._parse_salary_list("[5000.0, 12000.0]"), [5000, 12000])

    def test_parse_rejects_non_array(self) -> None:
        self.assertIsNone(self.agent._parse_salary_list("5000,12000"))

    def test_parse_rejects_empty_array(self) -> None:
        self.assertIsNone(self.agent._parse_salary_list("[]"))

    def test_parse_rejects_nonintegral_float(self) -> None:
        self.assertIsNone(self.agent._parse_salary_list("[5000.5]"))

    def test_parse_rejects_negative(self) -> None:
        self.assertIsNone(self.agent._parse_salary_list("[-5000]"))

    def test_parse_rejects_bool(self) -> None:
        self.assertIsNone(self.agent._parse_salary_list("[true, false]"))

    def test_parse_rejects_too_many(self) -> None:
        self.assertIsNone(self.agent._parse_salary_list("[" + ",".join(["1000"] * 100) + "]"))

    # --- _extract_salaries_via_model: fallbacks + success ------------------
    async def test_extract_disabled_by_flag(self) -> None:
        os.environ["JAVA_TAX_SALARY_USE_MODEL"] = "0"
        try:
            result = await self.agent._extract_salaries_via_model(
                {"question": "个人所得税 5000"}, _StubContext()
            )
        finally:
            os.environ.pop("JAVA_TAX_SALARY_USE_MODEL", None)
        self.assertIsNone(result)

    async def test_extract_disabled_when_llm_off(self) -> None:
        os.environ["AGENT_DEMO_USE_LLM"] = "false"
        try:
            result = await self.agent._extract_salaries_via_model(
                {"question": "个人所得税 5000"}, _StubContext()
            )
        finally:
            os.environ.pop("AGENT_DEMO_USE_LLM", None)
        self.assertIsNone(result)

    async def test_extract_empty_question(self) -> None:
        self.assertIsNone(
            await self.agent._extract_salaries_via_model({"question": ""}, _StubContext())
        )

    async def test_extract_success_parses_model_array(self) -> None:
        import source.solution.contestant_agent as ca

        class _FakeClient:
            def __init__(self, config):
                pass

            async def create(self, **kwargs):
                return {"choices": [{"message": {"content": "[5000, 12000, 25000]"}}]}

        class _FakeConfig:
            @staticmethod
            def from_env():
                return object()

        old_client, old_config = ca.ChatCompletionClient, ca.ModelConfig
        ca.ChatCompletionClient, ca.ModelConfig = _FakeClient, _FakeConfig
        os.environ["AGENT_DEMO_USE_LLM"] = "true"
        try:
            result = await self.agent._extract_salaries_via_model(
                {"question": "隐藏用例 5000 12000 25000"}, _StubContext()
            )
        finally:
            ca.ChatCompletionClient, ca.ModelConfig = old_client, old_config
            os.environ.pop("AGENT_DEMO_USE_LLM", None)
        self.assertEqual(result, [5000, 12000, 25000])

    async def test_extract_malformed_output_returns_none(self) -> None:
        import source.solution.contestant_agent as ca

        class _FakeClient:
            def __init__(self, config):
                pass

            async def create(self, **kwargs):
                return {"choices": [{"message": {"content": "抱歉，我无法确定"}}]}

        class _FakeConfig:
            @staticmethod
            def from_env():
                return object()

        old_client, old_config = ca.ChatCompletionClient, ca.ModelConfig
        ca.ChatCompletionClient, ca.ModelConfig = _FakeClient, _FakeConfig
        os.environ["AGENT_DEMO_USE_LLM"] = "true"
        try:
            result = await self.agent._extract_salaries_via_model(
                {"question": "隐藏用例 5000"}, _StubContext()
            )
        finally:
            ca.ChatCompletionClient, ca.ModelConfig = old_client, old_config
            os.environ.pop("AGENT_DEMO_USE_LLM", None)
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
