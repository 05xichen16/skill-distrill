"""Offline tests for ContestantAgent's explicit skill router.

The router is deliberately small and high-confidence: when a public contest
task clearly maps to an executable skill, the agent calls ``skill_run`` directly
and returns that skill's ``answer`` field. These tests keep that integration
stable without touching the model gateway.
"""
from __future__ import annotations

import os
import unittest

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
    def __init__(self, skills=None, answer="ROUTED") -> None:
        self.available_skills = [{"name": name} for name in (skills or ALL_ROUTED_SKILLS)]
        self.calls = []
        self.answer = answer

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
        self.assertEqual(route, ("sensitive_scan", {"zip_path": "sensitive_data_2_1.zip"}))

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

    def test_purchase_clean_route_uses_source_dir(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "采购数据清洗与汇总",
                "question": "clean purchase data",
                "files": ["./采购数据清洗与汇总/"],
            },
            context=_StubContext(),
        )
        self.assertEqual(route, ("purchase_clean_summary", {"source_dir": "./采购数据清洗与汇总"}))

    def test_po_audit_route_uses_source_dir(self) -> None:
        route = self.agent._explicit_skill_route(
            question={
                "title": "采购PO合规审计",
                "question": "audit POs",
                "files": ["./采购PO合规审计/"],
            },
            context=_StubContext(),
        )
        self.assertEqual(route, ("po_compliance_audit", {"source_dir": "./采购PO合规审计"}))

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


if __name__ == "__main__":
    unittest.main()
