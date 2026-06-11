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
import unittest

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


if __name__ == "__main__":
    unittest.main()
