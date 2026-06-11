"""Tests for the router's skill-answer quality guard.

Platform run #2 proved that a skill returning a *structurally dead* answer
(e.g. wiki_dialog's 30 placeholder elements) is silently submitted and scores
0, while the generic model loop would have earned partial credit. The guard
rejects shape-broken answers so the router falls back; it must NEVER reject a
well-formed answer (wrong content is fine — that is the model's job to beat).

Offline, standard-library unittest.
"""
from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import source.solution.contestant_agent as contestant_agent_module
from source.solution.contestant_agent import ContestantAgent


class _StubContext:
    def __init__(self, payload: str) -> None:
        self.available_skills = [{"name": "wiki_dialog"}, {"name": "date_normalize"}]
        self.payload = payload
        self.calls = []

    async def call_tool(self, name, args):
        self.calls.append((name, args))
        return self.payload


def _wiki_elements(count: int, empty: int) -> str:
    elements = []
    for index in range(count):
        reply = "" if index < empty else "真实回复%d" % index
        elements.append("Q%03d=>您好张总|||%s|||标准答复" % (index, reply))
    return json.dumps(elements, ensure_ascii=False)


class SkillAnswerGuardTest(unittest.TestCase):
    def setUp(self) -> None:
        self.agent = ContestantAgent()

    # --- generic ---------------------------------------------------------
    def test_empty_answer_rejected_by_default(self) -> None:
        self.assertIsNotNone(self.agent._skill_answer_guard("wiki_dialog", "   "))

    def test_empty_answer_legal_for_audit_and_interface(self) -> None:
        self.assertIsNone(self.agent._skill_answer_guard("po_compliance_audit", ""))
        self.assertIsNone(self.agent._skill_answer_guard("interface_test", ""))

    def test_unknown_skill_accepts_anything(self) -> None:
        self.assertIsNone(self.agent._skill_answer_guard("mock_summary_skill", "whatever"))

    # --- wiki_dialog -------------------------------------------------------
    def test_wiki_dialog_placeholders_rejected(self) -> None:
        answer = _wiki_elements(30, empty=30)
        self.assertIsNotNone(self.agent._skill_answer_guard("wiki_dialog", answer))

    def test_wiki_dialog_partial_placeholders_rejected_over_third(self) -> None:
        answer = _wiki_elements(30, empty=15)
        self.assertIsNotNone(self.agent._skill_answer_guard("wiki_dialog", answer))

    def test_wiki_dialog_healthy_accepted(self) -> None:
        answer = _wiki_elements(30, empty=2)
        self.assertIsNone(self.agent._skill_answer_guard("wiki_dialog", answer))

    def test_wiki_dialog_non_json_rejected(self) -> None:
        self.assertIsNotNone(self.agent._skill_answer_guard("wiki_dialog", "plain text"))

    # --- shape guards ------------------------------------------------------
    def test_date_normalize_dates_accepted_garbage_rejected(self) -> None:
        self.assertIsNone(
            self.agent._skill_answer_guard("date_normalize", "2026-05-06,2026-05-07")
        )
        self.assertIsNotNone(
            self.agent._skill_answer_guard("date_normalize", "2026-05-06,无法解析")
        )

    def test_java_tax_shape(self) -> None:
        good = 'openjdk version "21.0.11",' + ",".join(["90.00"] * 10)
        self.assertIsNone(self.agent._skill_answer_guard("java_tax_calculator", good))
        self.assertIsNotNone(
            self.agent._skill_answer_guard("java_tax_calculator", "90.00,590.00")
        )
        no_version = ",".join(["90.00"] * 11)
        self.assertIsNotNone(
            self.agent._skill_answer_guard("java_tax_calculator", no_version)
        )

    def test_sensitive_scan_shape(self) -> None:
        self.assertIsNone(self.agent._skill_answer_guard("sensitive_scan", "3,2,1,1"))
        self.assertIsNotNone(self.agent._skill_answer_guard("sensitive_scan", "3,2,1"))
        self.assertIsNotNone(self.agent._skill_answer_guard("sensitive_scan", "a,b,c,d"))

    def test_purchase_clean_summary_shape(self) -> None:
        self.assertIsNone(self.agent._skill_answer_guard("purchase_clean_summary", "11,0,13"))
        self.assertIsNotNone(self.agent._skill_answer_guard("purchase_clean_summary", "11,失败"))

    # --- po_compliance_audit -----------------------------------------------
    def test_po_audit_id_list_accepted(self) -> None:
        self.assertIsNone(
            self.agent._skill_answer_guard("po_compliance_audit", "PO-2026-0003,PO-2026-0013")
        )
        self.assertIsNone(self.agent._skill_answer_guard("po_compliance_audit", "PO-2026-0003"))

    def test_po_audit_bare_cot_rejected(self) -> None:
        cot = "好的，我先分析一下这道题。\n首先读取 purchase_orders_raw.csv，\n然后比较金额阈值。"
        self.assertIsNotNone(self.agent._skill_answer_guard("po_compliance_audit", cot))

    def test_po_audit_prose_single_line_rejected(self) -> None:
        self.assertIsNotNone(
            self.agent._skill_answer_guard("po_compliance_audit", "不合规的 PO 有 PO-2026-0003")
        )

    def test_po_audit_overlong_rejected(self) -> None:
        self.assertIsNotNone(self.agent._skill_answer_guard("po_compliance_audit", "A" * 2000))

    def test_system_issue_locator_shape(self) -> None:
        self.assertIsNone(
            self.agent._skill_answer_guard(
                "system_issue_locator", "用户管理,/api/users/save,接口路径配置错误、字段缺失"
            )
        )
        self.assertIsNotNone(self.agent._skill_answer_guard("system_issue_locator", "用户管理"))

    def test_prompt_learn_classify_shape(self) -> None:
        self.assertIsNone(
            self.agent._skill_answer_guard("prompt_learn_classify", "1PASS,2FAIL,3NOT_INVOLVED")
        )
        self.assertIsNotNone(
            self.agent._skill_answer_guard("prompt_learn_classify", "PASS,FAIL")
        )

    # --- wrong-but-well-formed answers MUST pass (never reject content) ----
    def test_guards_never_reject_wrong_content(self) -> None:
        self.assertIsNone(self.agent._skill_answer_guard("sensitive_scan", "0,0,0,0"))
        self.assertIsNone(
            self.agent._skill_answer_guard("date_normalize", "1999-01-01,1999-01-02")
        )


class RouterGuardIntegrationTest(unittest.IsolatedAsyncioTestCase):
    async def test_degraded_wiki_answer_falls_back(self) -> None:
        agent = ContestantAgent()
        payload = json.dumps({"answer": _wiki_elements(30, empty=30)}, ensure_ascii=False)
        context = _StubContext(payload)
        routed = await agent._try_explicit_skill_route(
            question={
                "title": "IDE 插件 FSE 数字人问答",
                "question": "answer all dialogs",
                "files": [
                    "./IDE插件FSE/persona.md",
                    "./IDE插件FSE/chat_history.db",
                    "./IDE插件FSE/source_access.json",
                    "./IDE插件FSE/dialog_tests_complex.json",
                ],
            },
            context=context,
        )
        self.assertIsNone(routed)  # guard rejected -> model loop takes over

    async def test_healthy_wiki_answer_routed(self) -> None:
        agent = ContestantAgent()
        payload = json.dumps({"answer": _wiki_elements(30, empty=0)}, ensure_ascii=False)
        context = _StubContext(payload)
        routed = await agent._try_explicit_skill_route(
            question={
                "title": "IDE 插件 FSE 数字人问答",
                "question": "answer all dialogs",
                "files": [
                    "./IDE插件FSE/persona.md",
                    "./IDE插件FSE/chat_history.db",
                    "./IDE插件FSE/source_access.json",
                    "./IDE插件FSE/dialog_tests_complex.json",
                ],
            },
            context=context,
        )
        self.assertEqual(routed, _wiki_elements(30, empty=0))


class GuardedModelAnswerTest(unittest.IsolatedAsyncioTestCase):
    """Model-loop answers replacing a failed skill go through the same guard:
    rejected -> one strict retry; the retry is returned even if still rejected,
    but an empty retry never replaces a non-empty answer (unless empty is
    legal for the skill)."""

    def setUp(self) -> None:
        self.agent = ContestantAgent()

    async def test_accepted_answer_returned_without_retry(self) -> None:
        async def fail_retry(user_content, *, enable_thinking):
            raise AssertionError("strict retry must not run for a well-formed answer")

        self.agent._strict_retry = fail_retry
        result = await self.agent._guarded_model_answer(
            "PO-2026-0003,PO-2026-0013",
            skill_name="po_compliance_audit",
            user_content="prompt",
            enable_thinking=False,
        )
        self.assertEqual(result, "PO-2026-0003,PO-2026-0013")

    async def test_rejected_cot_strict_retried(self) -> None:
        calls = []

        async def fake_retry(user_content, *, enable_thinking):
            calls.append(user_content)
            return "PO-2026-0003,PO-2026-0013"

        self.agent._strict_retry = fake_retry
        cot = "我们先分析题目要求。\n第一步读 CSV。\n第二步比对阈值。"
        result = await self.agent._guarded_model_answer(
            cot, skill_name="po_compliance_audit", user_content="prompt", enable_thinking=False
        )
        self.assertEqual(result, "PO-2026-0003,PO-2026-0013")
        self.assertEqual(len(calls), 1)

    async def test_retry_still_rejected_returns_retry(self) -> None:
        async def fake_retry(user_content, *, enable_thinking):
            return "还是一段分析文字"

        self.agent._strict_retry = fake_retry
        result = await self.agent._guarded_model_answer(
            "原始分析\n多行", skill_name="po_compliance_audit", user_content="p", enable_thinking=False
        )
        self.assertEqual(result, "还是一段分析文字")

    async def test_empty_retry_keeps_original_for_non_empty_ok_skill(self) -> None:
        async def fake_retry(user_content, *, enable_thinking):
            return "   "

        self.agent._strict_retry = fake_retry
        result = await self.agent._guarded_model_answer(
            "多行\n分析", skill_name="date_normalize", user_content="p", enable_thinking=False
        )
        self.assertEqual(result, "多行\n分析")

    async def test_retry_failure_keeps_original_answer(self) -> None:
        async def boom(user_content, *, enable_thinking):
            raise RuntimeError("gateway down")

        self.agent._strict_retry = boom
        result = await self.agent._guarded_model_answer(
            "多行\n分析", skill_name="po_compliance_audit", user_content="p", enable_thinking=False
        )
        self.assertEqual(result, "多行\n分析")


class SolveGuardIntegrationTest(unittest.IsolatedAsyncioTestCase):
    """solve() keeps the routed skill name across a skill crash so the model
    loop's replacement answer is gated by the same shape guard."""

    def setUp(self) -> None:
        self._old_use_llm = os.environ.get("AGENT_DEMO_USE_LLM")
        os.environ["AGENT_DEMO_USE_LLM"] = "true"

    def tearDown(self) -> None:
        if self._old_use_llm is None:
            os.environ.pop("AGENT_DEMO_USE_LLM", None)
        else:
            os.environ["AGENT_DEMO_USE_LLM"] = self._old_use_llm

    async def test_skill_crash_then_model_cot_is_gated(self) -> None:
        agent = ContestantAgent()

        class _CrashingSkillContext:
            available_skills = [{"name": "po_compliance_audit"}]
            available_tools: list = []
            available_agents: list = []
            allowed_file_paths: list = []

            async def call_tool(self, name, args):
                raise RuntimeError("skill exploded")

        async def fake_loop(**kwargs):
            return "好的，下面我来逐个分析 PO。\n首先看金额阈值。"

        async def fake_retry(user_content, *, enable_thinking):
            return "PO-2026-0003,PO-2026-0013"

        agent._run_model_loop = fake_loop
        agent._strict_retry = fake_retry
        answer = await agent.solve(
            question={
                "title": "采购PO合规审计",
                "question": "audit POs",
                "files": ["./采购PO合规审计/"],
            },
            context=_CrashingSkillContext(),
        )
        self.assertEqual(answer, "PO-2026-0003,PO-2026-0013")


class TruncationRetryTest(unittest.IsolatedAsyncioTestCase):
    """finish_reason=length without tool calls is never a final answer; the
    loop asks for the bare answer and accepts the next completion."""

    async def test_native_loop_rejects_truncated_final(self) -> None:
        agent = ContestantAgent()
        responses = [
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "被截断的裸推理过程，没有结论"},
                        "finish_reason": "length",
                    }
                ]
            },
            {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "PO-2026-0003"},
                        "finish_reason": "stop",
                    }
                ]
            },
        ]
        seen_messages = []

        class _FakeClient:
            def __init__(self, config) -> None:
                pass

            async def create(self, **kwargs):
                seen_messages.append([str(m.get("content")) for m in kwargs["messages"]])
                return responses.pop(0)

        class _FakeMCP:
            async def list_openai_tools(self, **kwargs):
                return []

        class _Context:
            mcp = _FakeMCP()
            allowed_tools: list = []
            allowed_agents: list = []

        with mock.patch.object(contestant_agent_module, "ChatCompletionClient", _FakeClient):
            answer = await agent._run_native_tool_loop(
                system_prompt="s", user_content="u", context=_Context(), enable_thinking=False
            )
        self.assertEqual(answer, "PO-2026-0003")
        # the second request carries the truncation instruction
        self.assertTrue(any("输出被截断" in content for content in seen_messages[1]))


if __name__ == "__main__":
    unittest.main()
