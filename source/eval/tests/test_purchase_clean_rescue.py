"""Rescue-pass tests for the purchase_clean_summary skill (task 2_1).

The deterministic extractors only know the public set's attachment wording, so
hidden variants get dropped ("cannot uniquely confirm"). The rescue pass lets
the model re-judge ONLY dropped POs under strict acceptance rules; accepted
POs are never re-judged, so the deterministic baseline cannot regress.

Offline, model mocked. Standard-library unittest.
"""
from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT / "source" / "solution" / "skills" / "purchase_clean_summary" / "scripts" / "run.py"
)

ENV_KEYS = ("MODEL_CHAT_COMPLETIONS_URL", "MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_NAME")


def _load_module():
    spec = importlib.util.spec_from_file_location("purchase_rescue", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_fixture(tmp: Path) -> Path:
    source = tmp / "purchase"
    source.mkdir()
    # PO-A is cleanly confirmable by code (vendor/category/amount/currency all
    # systematic). PO-B has a blank vendor_id and an attachment whose wording
    # the regex extractors do not recognise -> dropped by code.
    (source / "purchase_orders_raw.csv").write_text(
        "po_id,po_date,vendor_id,vendor_name,category_code,amount_raw,currency,business_purpose,item_description,attachment_ids\n"
        "PO-A,2026-04-01,V100,联创科技,COMPUTE_SERVICE,10000,CNY,GPU 算力,推理节点,\n"
        "PO-B,2026-04-02,,神州数据,DATA_GOVERNANCE,20000,CNY,数据血缘,主数据平台,ATT1\n",
        encoding="utf-8",
    )
    (source / "queries.csv").write_text(
        "query_id,vendor_id,category_code,currency\n"
        "1,V100,COMPUTE_SERVICE,CNY\n"
        "2,V200,DATA_GOVERNANCE,CNY\n",
        encoding="utf-8",
    )
    (source / "vendors.csv").write_text(
        "vendor_id,legal_name,brand_name,tax_id\n"
        "V100,联创科技有限公司,联创科技,91110000AAAA\n"
        "V200,神州数据股份有限公司,神州数据,91110000BBBB\n",
        encoding="utf-8",
    )
    (source / "category_taxonomy.csv").write_text(
        "category_code,name\n"
        "COMPUTE_SERVICE,算力服务\n"
        "DATA_GOVERNANCE,数据治理\n",
        encoding="utf-8",
    )
    (source / "attachment_manifest.csv").write_text(
        "attachment_id,file_path,kind\n"
        "ATT1,attachments/att1.txt,invoice\n",
        encoding="utf-8",
    )
    attachments = source / "attachments"
    attachments.mkdir()
    # Wording chosen to dodge the regex invoice markers (发票/Invoice/价税合计).
    (attachments / "att1.txt").write_text(
        "电子收款凭证 PO-B 收款方：神州数据股份有限公司 金额 CNY 20000 编码 91110000BBBB",
        encoding="utf-8",
    )
    return source


RULES = "1. 有效附件…… 10. 按 queries.csv 升序输出。"


class RescuePassTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        self._saved = {key: os.environ.pop(key, None) for key in ENV_KEYS}

    def tearDown(self) -> None:
        for key, value in self._saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value

    def _run(self, model_handler):
        if model_handler is None:
            self.module._model_config = lambda: None
        else:
            self.module._model_config = lambda: {
                "url": "u", "api_key": "k", "model": "m", "package_id": "",
            }
            self.module._call_model = model_handler
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_fixture(Path(tmp))
            return self.module.answer(
                {
                    "task_description": RULES,
                    "source_dir": str(source),
                    "do_ocr": False,
                    "_runtime": {},
                }
            )

    def test_dropped_po_rescued_with_valid_verdict(self) -> None:
        prompts = []

        def handler(config, prompt, timeout):
            prompts.append(prompt)
            return json.dumps(
                {
                    "countable": True,
                    "vendor_id": "V200",
                    "category_code": "DATA_GOVERNANCE",
                    "amount": 20000,
                    "currency": "CNY",
                    "reason": "收款凭证可唯一确认",
                }
            )

        result = self._run(handler)
        self.assertEqual(result["answer"], "10000,20000")
        self.assertEqual(result["rescued"], ["PO-B"])
        # Only the dropped PO went to the model; the rules text rode along.
        self.assertEqual(len(prompts), 1)
        self.assertIn("PO-B", prompts[0])
        self.assertIn(RULES, prompts[0])
        self.assertNotIn("PO-A,", prompts[0])

    def test_unknown_vendor_in_verdict_not_accepted(self) -> None:
        def handler(config, prompt, timeout):
            return json.dumps(
                {
                    "countable": True,
                    "vendor_id": "V999",  # not in vendors.csv
                    "category_code": "DATA_GOVERNANCE",
                    "amount": 20000,
                    "currency": "CNY",
                }
            )

        result = self._run(handler)
        self.assertEqual(result["answer"], "10000,0")
        self.assertEqual(result["rescued"], [])

    def test_not_countable_stays_dropped(self) -> None:
        def handler(config, prompt, timeout):
            return json.dumps({"countable": False, "reason": "金额无法唯一确认"})

        result = self._run(handler)
        self.assertEqual(result["answer"], "10000,0")
        self.assertEqual(result["rescued"], [])

    def test_model_failure_keeps_baseline(self) -> None:
        def handler(config, prompt, timeout):
            raise RuntimeError("gateway down")

        result = self._run(handler)
        self.assertEqual(result["answer"], "10000,0")
        self.assertEqual(result["rescued"], [])

    def test_offline_no_rescue(self) -> None:
        result = self._run(None)
        self.assertEqual(result["answer"], "10000,0")
        self.assertEqual(result["rescued"], [])


if __name__ == "__main__":
    unittest.main()
