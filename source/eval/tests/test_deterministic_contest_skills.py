"""Offline regression tests for deterministic contest skills.

These tests exercise the public fixture data without calling the model gateway.
For purchase image evidence, a tiny fake OCR reader supplies the visible text so
the cleaning logic is still tested end to end.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLIC_ROOT = REPO_ROOT / "publish" / "publish_V1"


def _load_module(relative: str, name: str):
    path = REPO_ROOT / relative
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_date_normalize_public_fixture() -> None:
    mod = _load_module(
        "source/solution/skills/date_normalize/scripts/run.py",
        "date_normalize_run",
    )
    result = mod.answer(
        {
            "message_file": "customer_date_messages.txt",
            "_runtime": {
                "question_dir": str(PUBLIC_ROOT),
                "allowed_file_paths": [str(PUBLIC_ROOT / "customer_date_messages.txt")],
            },
        }
    )
    assert result["answer"] == (
        "2026-12-21,2026-03-15,2026-07-22,2026-08-13,2026-11-08,"
        "2026-04-17,2026-06-15,2026-04-30,2025-05-06,2026-05-05,"
        "2026-05-11,2026-12-24,2026-12-28,2026-05-07,2026-07-29,"
        "2026-05-13,2025-05-06,2026-04-28,2026-06-01,2026-05-12,"
        "2026-05-13,2026-05-25,2026-01-09,2025-04-16,2026-02-14,"
        "2026-05-08,2026-05-20,2026-12-25,2026-12-23,2026-05-09"
    )


def test_system_issue_locator_public_fixture() -> None:
    mod = _load_module(
        "source/solution/skills/system_issue_locator/scripts/run.py",
        "system_issue_locator_run",
    )
    result = mod.answer(
        {
            "source_dir": "系统问题定位",
            "_runtime": {"question_dir": str(PUBLIC_ROOT), "allowed_file_paths": []},
        }
    )
    assert result["answer"] == "用户管理,/api/user/update,接口契约未同步、字段映射关系错误、枚举值转换异常"


def test_java_tax_calculator_public_fixture(monkeypatch) -> None:
    mod = _load_module(
        "source/solution/skills/java_tax_calculator/scripts/run.py",
        "java_tax_calculator_run",
    )
    monkeypatch.setattr(mod, "java_version_line", lambda: 'openjdk version "21.0.11"')
    task_description = (REPO_ROOT / "题目" / "Java个人所得税计算器.txt").read_text(encoding="utf-8")
    result = mod.answer(
        {
            "task_description": task_description,
            "source_file": "JavaSource_7_1.java",
            "_runtime": {
                "question_dir": str(PUBLIC_ROOT),
                "allowed_file_paths": [str(PUBLIC_ROOT / "JavaSource_7_1.java")],
            },
        }
    )
    assert result["answer"] == (
        'openjdk version "21.0.11",0.00,290.00,1340.00,3090.00,'
        "7840.00,9340.00,11090.00,22940.00,49940.00,207440.00"
    )


def test_po_compliance_audit_public_fixture() -> None:
    mod = _load_module(
        "source/solution/skills/po_compliance_audit/scripts/run.py",
        "po_compliance_audit_run",
    )
    result = mod.answer(
        {
            "source_dir": "采购PO合规审计",
            "_runtime": {"question_dir": str(PUBLIC_ROOT), "allowed_file_paths": []},
        }
    )
    assert result["answer"] == (
        "PO-2026-0003,PO-2026-0013,PO-2026-0014,PO-2026-0018,"
        "PO-2026-0021,PO-2026-0030,PO-2026-0034,PO-2026-0039,PO-2026-0042"
    )


def test_purchase_clean_summary_public_fixture_with_fake_ocr() -> None:
    mod = _load_module(
        "source/solution/skills/purchase_clean_summary/scripts/run.py",
        "purchase_clean_summary_run",
    )

    ocr_text = {
        "ATT-00001.png": "PO 编号 PO-2026-00003 录入供应商 北辰安全技术 录入金额 13704 CNY",
        "ATT-00002.png": "电子发票 PO 编号 PO-2026-00005 销售方 云杉云软件有限公司 统一社会信用代码 91440101MA5D0098P 价税合计 CNY 11233",
        "ATT-00003.png": "电子发票 PO 编号 PO-2026-00013 销售方 星河算力科技有限公司 统一社会信用代码 91110108MA01X0012A 价税合计 CNY 28893",
        "ATT-00004.png": "采购合同节选 PO 编号 PO-2026-00022 合同相对方 远岚会议服务有限公司 服务范围 会议场地 酒店安排 交通接驳 现场活动执行",
        "ATT-00016.png": "电子发票 PO 编号 PO-2026-00024 销售方 启衡智能设备有限公司 统一社会信用代码 91120116MA03H0099T 价税合计 CNY 55737 发票金额低于系统金额",
        "ATT-00018.png": "电子发票 PO 编号 PO-2026-00017 销售方 云杉云软件有限公司 统一社会信用代码 91440101MA5D0098P 价税合计 USD 29355 发票币种不是 CNY",
        "ATT-00020.png": "PO 编号 PO-2026-00036 录入供应商 启明 录入金额 62274 CNY",
        "ATT-00021.png": "PO 编号 PO-2026-00024 录入供应商 启衡智能设备 录入金额 58180 CNY",
        "ATT-00022.png": "PO 编号 PO-2026-00017 录入供应商 Spruce SaaS 录入金额 29355 CNY",
        "ATT-00023.png": "电子发票 PO 编号 PO-2026-X107 销售方 云桥会议服务有限公司 价税合计 CNY 44667 该附件 PO 编号与当前采购记录不一致",
        "ATT-00024.png": "采购比价记录 PO 编号 PO-2026-00044 报价 CNY 19786 报价记录不能作为付款金额凭证",
        "ATT-00025.png": "PO 编号 PO-2026-00045 录入供应商 星火算力科技 录入金额 大概 16397 左右",
    }

    def fake_ocr(path: str) -> str:
        return ocr_text.get(Path(path).name, "")

    result = mod.answer(
        {
            "source_dir": "采购数据清洗与汇总",
            "_runtime": {"question_dir": str(PUBLIC_ROOT), "allowed_file_paths": []},
        },
        ocr_reader=fake_ocr,
    )
    assert result["answer"] == "122377,128945,97826,104474,60723,150997,176952,161401,120853,26393,118404,99654"
