"""Hybrid-audit behavior tests for the po_compliance_audit skill (task 3_2).

Platform run #2 scored 0/15 because every semantic judgment was keyword-coded.
These tests pin the new behavior offline (model mocked):
  * the amount threshold comes from the question text, not a literal
  * unknown status words go through one batched model classification
  * the per-PO deep audit consumes the model's structured verdict while role /
    validity-window / date checks stay in code (a non-VP approval the model
    "approves" must still fail)
  * expanded date formats parse
  * model failure falls back to the legacy code path

Standard-library unittest.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from datetime import date
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT / "source" / "solution" / "skills" / "po_compliance_audit" / "scripts" / "run.py"
)

ENV_KEYS = (
    "MODEL_CHAT_COMPLETIONS_URL",
    "MODEL_BASE_URL",
    "MODEL_API_KEY",
    "MODEL_NAME",
    "PO_AUDIT_USE_LLM",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("po_audit_hybrid", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fixture(tmp: Path) -> Path:
    source = tmp / "audit"
    source.mkdir()
    (source / "purchase_orders_raw.csv").write_text(
        "po_id,po_date,status,amount_cny,vendor_id,vendor_name,service_items,evidence_ids\n"
        "PO-1,2026-03-10,已终审归档,80000,V1,联创科技,服务器,E1\n"  # not in keyword lists
        "PO-2,2026-03-10,已完成,30000,V1,联创科技,服务器,E1\n"  # below threshold
        "PO-3,2026-03-10,审批中,90000,V1,联创科技,服务器,E1\n"  # non-terminal
        "PO-4,2026-03-10,已完成,120000,V1,联创科技,云主机,E2\n",
        encoding="utf-8",
    )
    (source / "vendors.csv").write_text(
        "vendor_id,vendor_name,service_scope\n"
        "V1,联创科技,服务器、交换机\n",
        encoding="utf-8",
    )
    (source / "people_roles.csv").write_text(
        "email,role,valid_from,valid_to\n"
        "vp@corp.com,VP,2026-01-01,2026-12-31\n"
        "mgr@corp.com,Manager,2026-01-01,2026-12-31\n"
        "oldvp@corp.com,VP,2025-01-01,2025-12-31\n",
        encoding="utf-8",
    )
    (source / "approval_evidence.csv").write_text(
        "evidence_id,file_path\n"
        "E1,evidence/e1.txt\n"
        "E2,evidence/e2.txt\n",
        encoding="utf-8",
    )
    evidence = source / "evidence"
    evidence.mkdir()
    (evidence / "e1.txt").write_text(
        "From: 张总 <vp@corp.com>\nDate: 2026.03.05\n关于 PO-1：服务器采购一事，准予执行。\n",
        encoding="utf-8",
    )
    (evidence / "e2.txt").write_text(
        "From: 王经理 <mgr@corp.com>\nDate: 2026-03-05\nPO-4 云主机采购，同意。\n",
        encoding="utf-8",
    )
    return source


TASK_TEXT_60K = "只有状态有效且 amount_cny 达到或超过 60000 CNY 的 PO 才进入合规深审。"


class ThresholdAndDatesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_threshold_parsed_from_question(self) -> None:
        self.assertEqual(self.module.parse_amount_threshold(TASK_TEXT_60K), 60000)
        self.assertEqual(
            self.module.parse_amount_threshold("达到或超过 50,000 元的 PO"), 50000
        )
        self.assertEqual(
            self.module.parse_amount_threshold("审计 amount_cny 在 70,000 CNY 以上的 PO"), 70000
        )
        self.assertIsNone(self.module.parse_amount_threshold("没有提到任何数"))

    def test_expanded_date_formats(self) -> None:
        cases = {
            "2026年3月5日": date(2026, 3, 5),
            "2026-03-05": date(2026, 3, 5),
            "2026/3/5": date(2026, 3, 5),
            "2026.03.05": date(2026, 3, 5),
            "Mar 5, 2026": date(2026, 3, 5),
            "March 5 2026": date(2026, 3, 5),
            "5 March 2026": date(2026, 3, 5),
            "03/05/2026": date(2026, 3, 5),
            "Wed 2026-03-05": date(2026, 3, 5),
        }
        for text, expected in cases.items():
            self.assertEqual(self.module.parse_date_text(text), expected, msg=text)

    def test_status_keyword_tristate(self) -> None:
        self.assertTrue(self.module.is_terminal_status("已付款"))
        self.assertFalse(self.module.is_terminal_status("审批中"))
        self.assertTrue(self.module.is_terminal_status("已终审归档"))


class HybridAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self._saved = {key: os.environ.pop(key, None) for key in ENV_KEYS}

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _run(self, model_handler, task_description=TASK_TEXT_60K):
        self.module._model_config = lambda: {
            "url": "u", "api_key": "k", "model": "m", "package_id": "",
        }
        self.module._call_model = model_handler
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            return self.module.answer(
                {
                    "task_description": task_description,
                    "source_dir": str(source),
                    "_runtime": {},
                }
            )

    def test_llm_verdicts_with_code_role_validation(self) -> None:
        def handler(config, prompt, timeout):
            if "状态字段需要分类" in prompt:
                return json.dumps({"已终审归档": "terminal"}, ensure_ascii=False)
            if "批量审查" in prompt:
                # VP approval, in-window date, all items -> compliant
                return json.dumps(
                    {
                        "PO-1": {
                            "items_all_in_scope": True,
                            "approvals": [
                                {
                                    "sender_email": "vp@corp.com",
                                    "date": "2026-03-05",
                                    "explicitly_approves_this_po": True,
                                    "approves_all_items": True,
                                }
                            ],
                        },
                        "PO-4": {
                            # The model says "approved", but the sender is a Manager:
                            # code-side role validation must still fail this PO.
                            "items_all_in_scope": False,
                            "approvals": [
                                {
                                    "sender_email": "mgr@corp.com",
                                    "date": "2026-03-05",
                                    "explicitly_approves_this_po": True,
                                    "approves_all_items": True,
                                }
                            ],
                        },
                    }
                )
            raise AssertionError("unexpected prompt")

        result = self._run(handler)
        # PO-1: terminal (via LLM status), 80k >= 60k, compliant -> not listed.
        # PO-2: 30k < 60k threshold -> never deep-audited.
        # PO-3: non-terminal -> skipped.
        # PO-4: scope fails + approval by Manager rejected in code -> listed.
        self.assertEqual(result["answer"], "PO-4")
        self.assertEqual(result["threshold"], 60000)
        self.assertEqual(result["deep_audited"], 2)

    def test_expired_vp_rejected_by_code(self) -> None:
        def handler(config, prompt, timeout):
            if "状态字段需要分类" in prompt:
                return json.dumps({"已终审归档": "terminal"}, ensure_ascii=False)
            if "批量审查" in prompt:
                return json.dumps(
                    {
                        "PO-1": {
                            "items_all_in_scope": True,
                            "approvals": [
                                {
                                    "sender_email": "oldvp@corp.com",  # VP expired in 2025
                                    "date": "2026-03-05",
                                    "explicitly_approves_this_po": True,
                                    "approves_all_items": True,
                                }
                            ],
                        },
                        "PO-4": {
                            "items_all_in_scope": True,
                            "approvals": [
                                {
                                    "sender_email": "oldvp@corp.com",
                                    "date": "2026-03-05",
                                    "explicitly_approves_this_po": True,
                                    "approves_all_items": True,
                                }
                            ],
                        },
                    }
                )
            raise AssertionError("unexpected prompt")

        result = self._run(handler)
        # Both deep-audited POs only carry an expired-VP approval -> both bad.
        self.assertEqual(result["answer"], "PO-1,PO-4")

    def test_status_model_can_override_keyword_hit(self) -> None:
        def handler(config, prompt, timeout):
            if "状态字段需要分类" in prompt:
                return json.dumps(
                    {
                        "已终审归档": "non_terminal",
                        "已完成": "terminal",
                        "审批中": "non_terminal",
                        "已完成待法务复核": "non_terminal",
                    },
                    ensure_ascii=False,
                )
            raise AssertionError("no PO should reach deep audit")

        self.module._model_config = lambda: {
            "url": "u", "api_key": "k", "model": "m", "package_id": "",
        }
        self.module._call_model = handler
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            csv_path = source / "purchase_orders_raw.csv"
            csv_path.write_text(
                csv_path.read_text(encoding="utf-8").replace(
                    "PO-4,2026-03-10,已完成,120000",
                    "PO-4,2026-03-10,已完成待法务复核,120000",
                ),
                encoding="utf-8",
            )
            result = self.module.answer(
                {"task_description": TASK_TEXT_60K, "source_dir": str(source), "_runtime": {}}
            )

        self.assertEqual(result["deep_audited"], 0)
        self.assertEqual(result["answer"], "")

    def test_batch_audit_can_overrule_code_compliant_po(self) -> None:
        def handler(config, prompt, timeout):
            if "状态字段需要分类" in prompt:
                return json.dumps({"已终审归档": "terminal"}, ensure_ascii=False)
            if "批量审查" in prompt:
                return json.dumps(
                    {
                        "PO-1": {
                            "items_all_in_scope": "false",
                            "approvals": [
                                {
                                    "sender_email": "vp@corp.com",
                                    "date": "2026-03-05",
                                    "explicitly_approves_this_po": "true",
                                    "approves_all_items": "true",
                                }
                            ],
                        }
                    }
                )
            raise AssertionError("unexpected prompt")

        self.module._model_config = lambda: {
            "url": "u", "api_key": "k", "model": "m", "package_id": "",
        }
        self.module._call_model = handler
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            csv_path = source / "purchase_orders_raw.csv"
            csv_path.write_text(
                csv_path.read_text(encoding="utf-8").replace(
                    "PO-4,2026-03-10,已完成,120000",
                    "PO-4,2026-03-10,已完成,30000",
                ),
                encoding="utf-8",
            )
            (source / "evidence" / "e1.txt").write_text(
                "From: 张总 <vp@corp.com>\n"
                "Date: 2026.03.05\n"
                "关于 PO-1：服务器采购，完整清单均已看过并批准。\n",
                encoding="utf-8",
            )
            result = self.module.answer(
                {"task_description": TASK_TEXT_60K, "source_dir": str(source), "_runtime": {}}
            )

        self.assertEqual(result["answer"], "PO-1")
        self.assertEqual(result["batch_judged"], 1)

    def test_threshold_can_come_from_audit_rules_file(self) -> None:
        self.module._model_config = lambda: None
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            (source / "audit_rules.md").write_text(
                "只审计状态有效且 amount_cny 在 100000 CNY 以上的 PO。\n",
                encoding="utf-8",
            )
            result = self.module.answer(
                {"task_description": "请按规则文件审计 PO", "source_dir": str(source), "_runtime": {}}
            )

        self.assertEqual(result["threshold"], 100000)
        self.assertEqual(result["deep_audited"], 1)

    def test_model_failure_falls_back_to_code_path(self) -> None:
        def handler(config, prompt, timeout):
            raise RuntimeError("gateway down")

        result = self._run(handler)
        # Status LLM also fails -> 已终审归档 unknown -> treated non-terminal, so
        # only PO-4 (已完成) is deep-audited, judged by the legacy code rules:
        # scope 云主机 not in 服务器、交换机 -> bad. The answer stays well-formed.
        self.assertEqual(result["answer"], "PO-4")
        self.assertTrue(any("code fallback" in w or "classification call failed" in w
                            for w in result["warnings"]))

    def test_offline_runs_pure_code_path(self) -> None:
        self.module._model_config = lambda: None
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            result = self.module.answer(
                {"task_description": "", "source_dir": str(source), "_runtime": {}}
            )
        # threshold defaults to 50000; PO-4 deep-audited and bad via code rules.
        self.assertEqual(result["threshold"], 50000)
        self.assertIn("PO-4", result["answer"])

    def test_llm_can_be_disabled_for_exact_grader(self) -> None:
        os.environ["PO_AUDIT_USE_LLM"] = "0"
        self.module._model_config = lambda: {
            "url": "u", "api_key": "k", "model": "m", "package_id": "",
        }

        def must_not_call(config, prompt, timeout):
            raise AssertionError("PO_AUDIT_USE_LLM=0 must skip model calls")

        self.module._call_model = must_not_call
        try:
            with tempfile.TemporaryDirectory() as tmp:
                source = _write_fixture(Path(tmp))
                result = self.module.answer(
                    {"task_description": TASK_TEXT_60K, "source_dir": str(source), "_runtime": {}}
                )
        finally:
            os.environ.pop("PO_AUDIT_USE_LLM", None)

        self.assertIn("PO-4", result["answer"])
        self.assertTrue(any("disabled" in w for w in result["warnings"]))


class DeadlineSelfProtectionTest(unittest.TestCase):
    """A tiny SKILL_BUDGET_SECONDS must degrade deep audits to the code rules
    (no per-PO model calls) yet still emit a well-formed answer."""

    def setUp(self) -> None:
        self.module = _load_module()
        self._saved = {key: os.environ.pop(key, None) for key in ENV_KEYS}

    def tearDown(self) -> None:
        os.environ.pop("SKILL_BUDGET_SECONDS", None)
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def test_tiny_budget_skips_deep_audit_llm(self) -> None:
        os.environ["SKILL_BUDGET_SECONDS"] = "25"  # deadline = now + 10s, under the 15s floor
        status_timeouts = []

        def handler(config, prompt, timeout):
            if "状态字段需要分类" in prompt:
                status_timeouts.append(timeout)
                return json.dumps({"已终审归档": "terminal"}, ensure_ascii=False)
            raise AssertionError("deep audit must not call the model past the deadline")

        self.module._model_config = lambda: {
            "url": "u", "api_key": "k", "model": "m", "package_id": "",
        }
        self.module._call_model = handler
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            result = self.module.answer(
                {"task_description": TASK_TEXT_60K, "source_dir": str(source), "_runtime": {}}
            )

        # Both deep-audited POs (PO-1 via LLM status, PO-4) fell back to the
        # code rules. PO-1's "准予执行" approval is now recognized by the
        # deterministic path; PO-4's scope still fails.
        self.assertEqual(result["answer"], "PO-4")
        self.assertTrue(any("deadline" in w for w in result["warnings"]))
        # the batched status call still ran, with its timeout clamped to the budget
        self.assertTrue(status_timeouts and status_timeouts[0] <= 10)


if __name__ == "__main__":
    unittest.main()
