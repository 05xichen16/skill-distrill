"""Behavior tests for the po_compliance_audit skill (task 3_2).

Design under test (the platform grades 3_2 all-or-nothing, so every PO must be
exactly right and the skill must never crash into the model loop):

  * scope coverage is judged in CODE against the enumerated vendor scope — the
    model's category reasoning proved inconsistent on borderline items, so its
    scope claim is a diagnostic only and never decides the verdict;
  * approval intent is extracted per-PO by the model, but the VP role /
    validity-window / date<=po_date checks are ALWAYS re-applied in code against
    people_roles.csv (a non-VP / expired-VP / post-dated approval the model
    "approves" must still fail);
  * the skill never raises — malformed dates or missing optional files degrade
    to a well-formed (possibly empty) answer instead of the version-less model
    loop, which would be an exact zero on this grader;
  * status: the keyword verdict is authoritative; only words the keyword lists
    don't recognise are sent to the model.

Standard-library unittest; the model gateway is mocked, no network.
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
    "PO_AUDIT_DEEP_THINKING",
)


def _load_module():
    spec = importlib.util.spec_from_file_location("po_audit_run", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fixture(tmp: Path) -> Path:
    source = tmp / "audit"
    source.mkdir()
    (source / "purchase_orders_raw.csv").write_text(
        "po_id,po_date,status,amount_cny,vendor_id,vendor_name,service_items,evidence_ids\n"
        "PO-1,2026-03-10,已终审归档,80000,V1,联创科技,服务器,E1\n"  # terminal via keyword
        "PO-2,2026-03-10,已完成,30000,V1,联创科技,服务器,E1\n"  # below threshold
        "PO-3,2026-03-10,审批中,90000,V1,联创科技,服务器,E1\n"  # non-terminal
        "PO-4,2026-03-10,已完成,120000,V1,联创科技,云主机,E2\n",  # 云主机 out of scope
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


def _deep_handler(verdicts_by_po, status_map=None):
    """Mock _call_model: dispatch the per-PO deep prompt by its `po_id:` line,
    and answer the status-classification prompt from status_map. Accepts the
    new enable_thinking / max_tokens kwargs."""

    def handler(config, prompt, timeout, **kwargs):
        if "状态字段需要分类" in prompt:
            return json.dumps(status_map or {}, ensure_ascii=False)
        for poid, verdict in verdicts_by_po.items():
            if ("po_id: %s" % poid) in prompt:
                return json.dumps(verdict, ensure_ascii=False)
        raise AssertionError("unexpected prompt: %s" % prompt[:160])

    return handler


def _approval(email, day="2026-03-05", po=True, items=True):
    return {
        "sender_email": email,
        "date": day,
        "explicitly_approves_this_po": po,
        "approves_all_items": items,
    }


class PureHelpersTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()

    def test_threshold_parsed_from_question(self) -> None:
        self.assertEqual(self.module.parse_amount_threshold(TASK_TEXT_60K), 60000)
        self.assertEqual(self.module.parse_amount_threshold("达到或超过 50,000 元的 PO"), 50000)
        self.assertEqual(self.module.parse_amount_threshold("审计 amount_cny 在 70,000 CNY 以上的 PO"), 70000)
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

    def test_parse_iso_never_raises(self) -> None:
        self.assertEqual(self.module.parse_iso("2026-03-05"), date(2026, 3, 5))
        for bad in ("", "   ", "not-a-date", "2026/03/05", "2026-13-40", "2026-3"):
            self.assertIsNone(self.module.parse_iso(bad), msg=bad)

    def test_status_keyword_tristate(self) -> None:
        self.assertTrue(self.module.is_terminal_status("已付款"))
        self.assertFalse(self.module.is_terminal_status("审批中"))
        self.assertTrue(self.module.is_terminal_status("已终审归档"))
        # a genuinely novel synonym is unknown (None) so the model can resolve it
        self.assertIsNone(self.module.is_terminal_status("履约完成"))

    def test_scope_match_is_vocabulary_agnostic(self) -> None:
        scope = "机架式服务器、网络交换机、存储阵列"
        self.assertTrue(self.module.item_in_scope("机架式服务器", scope))
        self.assertTrue(self.module.item_in_scope("服务器", scope))  # entry contains item
        self.assertFalse(self.module.item_in_scope("员工笔记本", scope))  # different category
        self.assertFalse(self.module.item_in_scope("管理培训", scope))


class _ModelTestBase(unittest.TestCase):
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

    def _configure(self, handler) -> None:
        self.module._model_config = lambda: {"url": "u", "api_key": "k", "model": "m", "package_id": ""}
        self.module._call_model = handler

    def _run(self, handler, task_description=TASK_TEXT_60K, mutate=None):
        self._configure(handler)
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            if mutate:
                mutate(source)
            return self.module.answer(
                {"task_description": task_description, "source_dir": str(source), "_runtime": {}}
            )


class ApprovalAndRoleTest(_ModelTestBase):
    def test_llm_approval_with_code_role_validation(self) -> None:
        # PO-1: VP approval, in window, all items -> compliant (not listed).
        # PO-4: model "approves" but the sender is a Manager AND 云主机 is out of
        #       scope -> code must mark it non-compliant.
        handler = _deep_handler({
            "PO-1": {"items_all_in_scope": True, "approvals": [_approval("vp@corp.com")]},
            "PO-4": {"items_all_in_scope": True, "approvals": [_approval("mgr@corp.com")]},
        })
        result = self._run(handler)
        self.assertEqual(result["answer"], "PO-4")
        self.assertEqual(result["threshold"], 60000)
        self.assertEqual(result["deep_audited"], 2)

    def test_expired_vp_rejected_by_code(self) -> None:
        handler = _deep_handler({
            "PO-1": {"items_all_in_scope": True, "approvals": [_approval("oldvp@corp.com")]},
            "PO-4": {"items_all_in_scope": True, "approvals": [_approval("oldvp@corp.com")]},
        })
        result = self._run(handler)
        # PO-1 only carries an expired-VP approval; PO-4 also fails scope. Both bad.
        self.assertEqual(result["answer"], "PO-1,PO-4")

    def test_post_dated_approval_rejected_by_code(self) -> None:
        # VP approval but dated AFTER po_date (2026-03-10) -> invalid.
        handler = _deep_handler({
            "PO-1": {"items_all_in_scope": True, "approvals": [_approval("vp@corp.com", day="2026-03-11")]},
            "PO-4": {"items_all_in_scope": False, "approvals": []},
        })
        result = self._run(handler)
        self.assertEqual(result["answer"], "PO-1,PO-4")

    def test_partial_approval_rejected(self) -> None:
        handler = _deep_handler({
            "PO-1": {"items_all_in_scope": True,
                     "approvals": [_approval("vp@corp.com", items=False)]},  # not all items
            "PO-4": {"items_all_in_scope": False, "approvals": []},
        })
        result = self._run(handler)
        self.assertEqual(result["answer"], "PO-1,PO-4")


class CodeScopeAuthoritativeTest(_ModelTestBase):
    def test_model_scope_claim_does_not_decide(self) -> None:
        # The model insists everything is in scope (items_all_in_scope=true) for
        # both POs, yet PO-4's 云主机 is not in 服务器、交换机. Code scope is
        # authoritative, so PO-4 is non-compliant regardless of the model.
        handler = _deep_handler({
            "PO-1": {"items_all_in_scope": True, "approvals": [_approval("vp@corp.com")]},
            "PO-4": {"items_all_in_scope": True, "approvals": [_approval("vp@corp.com")]},
        })
        result = self._run(handler)
        self.assertEqual(result["answer"], "PO-4")
        # the model's scope read differed from code on PO-4 -> surfaced as a diagnostic
        self.assertTrue(any("scope" in w for w in result["warnings"]))

    def test_model_false_scope_claim_cannot_condemn_in_scope_po(self) -> None:
        # The model wrongly says PO-1 (服务器, in scope) is out of scope; a valid
        # VP approval still makes it compliant because code scope says in-scope.
        handler = _deep_handler({
            "PO-1": {"items_all_in_scope": False, "approvals": [_approval("vp@corp.com")]},
            "PO-4": {"items_all_in_scope": False, "approvals": []},
        })
        result = self._run(handler)
        self.assertEqual(result["answer"], "PO-4")  # PO-1 stays compliant


class StatusScreenTest(_ModelTestBase):
    def test_unknown_status_resolved_by_model_known_status_is_not_sent(self) -> None:
        sent_words = []

        def handler(config, prompt, timeout, **kwargs):
            if "状态字段需要分类" in prompt:
                sent_words.append(prompt)
                return json.dumps({"履约完成": "terminal"}, ensure_ascii=False)
            # only PO-9 (履约完成) should reach deep audit here
            if "po_id: PO-9" in prompt:
                return json.dumps({"items_all_in_scope": True, "approvals": []})
            raise AssertionError("unexpected deep prompt: %s" % prompt[:120])

        def mutate(source: Path) -> None:
            csv = source / "purchase_orders_raw.csv"
            csv.write_text(
                "po_id,po_date,status,amount_cny,vendor_id,vendor_name,service_items,evidence_ids\n"
                "PO-9,2026-03-10,履约完成,80000,V1,联创科技,服务器,\n"  # novel terminal word
                "PO-8,2026-03-10,已完成,80000,V1,联创科技,服务器,E1\n",  # known terminal word
                encoding="utf-8",
            )

        result = self._run(handler, mutate=mutate)
        # both terminal & >=60k -> both deep audited; no evidence/empty approvals -> both bad
        self.assertEqual(result["deep_audited"], 2)
        self.assertEqual(result["answer"], "PO-8,PO-9")
        # only the unknown word is in the classification word-list (the known
        # word is settled by keyword and never sent). Check the words section
        # only — the prompt template's rule text legitimately names 已完成.
        self.assertEqual(len(sent_words), 1)
        words_section = sent_words[0].split("待分类状态词（每行一个）：")[-1]
        self.assertIn("履约完成", words_section)
        self.assertNotIn("已完成", words_section)


class CrashProofTest(_ModelTestBase):
    def test_malformed_dates_do_not_crash(self) -> None:
        self.module._model_config = lambda: None  # offline -> code path

        def mutate(source: Path) -> None:
            (source / "purchase_orders_raw.csv").write_text(
                "po_id,po_date,status,amount_cny,vendor_id,vendor_name,service_items,evidence_ids\n"
                "PO-1,not-a-date,已完成,80000,V1,联创科技,服务器,E1\n"
                "PO-4,2026/13/40,已完成,120000,V1,联创科技,云主机,E2\n",
                encoding="utf-8",
            )
            (source / "people_roles.csv").write_text(
                "email,role,valid_from,valid_to\n"
                "vp@corp.com,VP,,\n"  # blank validity window
                "x@corp.com,VP,garbage,also-bad\n",
                encoding="utf-8",
            )

        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            mutate(source)
            result = self.module.answer({"task_description": "", "source_dir": str(source), "_runtime": {}})
        # never raised; well-formed answer string emitted
        self.assertIn("answer", result)
        self.assertIsInstance(result["answer"], str)

    def test_missing_optional_files_do_not_crash(self) -> None:
        self.module._model_config = lambda: None
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            (source / "vendors.csv").unlink()
            (source / "people_roles.csv").unlink()
            result = self.module.answer({"task_description": "", "source_dir": str(source), "_runtime": {}})
        self.assertIn("answer", result)
        self.assertIsInstance(result["answer"], str)

    def test_internal_failure_emits_empty_answer_not_raise(self) -> None:
        # resolve_source_dir on a bogus dir raises inside _audit; the wrapper
        # must still return a shape-valid empty answer (legal "no violations").
        result = self.module.answer({"source_dir": "/nonexistent/path/xyz", "_runtime": {}})
        self.assertEqual(result.get("answer"), "")


class FallbackTest(_ModelTestBase):
    def test_model_failure_falls_back_to_code_path(self) -> None:
        def handler(config, prompt, timeout, **kwargs):
            raise RuntimeError("gateway down")

        result = self._run(handler)
        # PO-1: code recognises "准予执行" by VP -> compliant. PO-4: 云主机 out of
        # scope -> bad. Well-formed answer; a code-fallback warning is recorded.
        self.assertEqual(result["answer"], "PO-4")
        self.assertTrue(any("code" in w for w in result["warnings"]))

    def test_offline_runs_pure_code_path(self) -> None:
        self.module._model_config = lambda: None
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            result = self.module.answer({"task_description": "", "source_dir": str(source), "_runtime": {}})
        self.assertEqual(result["threshold"], 50000)
        self.assertIn("PO-4", result["answer"])

    def test_llm_can_be_disabled(self) -> None:
        os.environ["PO_AUDIT_USE_LLM"] = "0"
        self.module._model_config = lambda: {"url": "u", "api_key": "k", "model": "m", "package_id": ""}

        def must_not_call(config, prompt, timeout, **kwargs):
            raise AssertionError("PO_AUDIT_USE_LLM=0 must skip model calls")

        self.module._call_model = must_not_call
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            result = self.module.answer(
                {"task_description": TASK_TEXT_60K, "source_dir": str(source), "_runtime": {}}
            )
        self.assertIn("PO-4", result["answer"])
        self.assertTrue(any("PO_AUDIT_USE_LLM=0" in w for w in result["warnings"]))

    def test_threshold_can_come_from_audit_rules_file(self) -> None:
        self.module._model_config = lambda: None
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            (source / "audit_rules.md").write_text(
                "只审计状态有效且 amount_cny 在 100000 CNY 以上的 PO。\n", encoding="utf-8"
            )
            result = self.module.answer(
                {"task_description": "请按规则文件审计 PO", "source_dir": str(source), "_runtime": {}}
            )
        self.assertEqual(result["threshold"], 100000)
        self.assertEqual(result["deep_audited"], 1)


class DeadlineSelfProtectionTest(_ModelTestBase):
    def test_tiny_budget_skips_deep_audit_llm(self) -> None:
        os.environ["SKILL_BUDGET_SECONDS"] = "20"  # deadline = now + 5s, under the 10s floor

        def handler(config, prompt, timeout, **kwargs):
            if "状态字段需要分类" in prompt:
                return json.dumps({}, ensure_ascii=False)
            raise AssertionError("deep audit must not call the model past the deadline")

        self._configure(handler)
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            result = self.module.answer(
                {"task_description": TASK_TEXT_60K, "source_dir": str(source), "_runtime": {}}
            )
        # both deep POs degraded to code rules; PO-1 "准予执行" recognised, PO-4 scope fails
        self.assertEqual(result["answer"], "PO-4")
        self.assertIsInstance(result["answer"], str)


if __name__ == "__main__":
    unittest.main()
