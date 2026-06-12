"""Verify 2_1 rename-variant: discovery path must reproduce the public answer.

Runs purchase_clean_summary twice with the same fake OCR transcripts (copied
from the offline public-fixture test; no gateway, no rescue pass):

  1. public dir  (exact-filename pass, the pre-change behaviour) -> baseline
  2. variant_renamed/ (content-discovery pass) -> must equal the baseline

Both must equal the known public reference output byte-for-byte.

Stdlib only. PYTHONIOENCODING=utf-8 expected. ASCII-only prints.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RUN_PY = REPO / "source" / "solution" / "skills" / "purchase_clean_summary" / "scripts" / "run.py"
PUBLIC = REPO / "publish" / "publish_V1" / "采购数据清洗与汇总"
VARIANT = HERE / "variant_renamed"

EXPECTED = "122377,128945,97826,104474,60723,150997,176952,161401,120853,26393,118404,99654"

# Same transcripts the offline public-fixture test uses (keyed by image name).
OCR_TEXT = {
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


def load_skill():
    spec = importlib.util.spec_from_file_location("pcs", RUN_PY)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module._model_config = lambda: None  # offline: no rescue pass
    return module


def fake_ocr(path: str) -> str:
    return OCR_TEXT.get(Path(path).name, "")


def run_case(module, label: str, source_dir: Path) -> str:
    _, tables, _ = module.resolve_source_tables(str(source_dir), {})
    print("[%s] resolved tables:" % label)
    for table in module.ALL_TABLES:
        name = Path(tables[table]).name if table in tables else "(missing)"
        print("    %-20s -> %s" % (table, name))
    result = module.answer(
        {"task_description": "", "source_dir": str(source_dir), "_runtime": {}},
        ocr_reader=fake_ocr,
    )
    answer = result["answer"]
    verdict = "PASS" if answer == EXPECTED else "FAIL"
    print("[%s] answer  : %s" % (label, answer))
    print("[%s] expected: %s" % (label, EXPECTED))
    print("[%s] %s (included=%d, rescued=%d)" % (
        label, verdict, len(result.get("included") or []), len(result.get("rescued") or [])))
    return verdict


def main() -> int:
    if not VARIANT.is_dir():
        print("variant_renamed/ missing; run make_variant.py first")
        return 2
    verdicts = [
        run_case(load_skill(), "public ", PUBLIC),
        run_case(load_skill(), "variant", VARIANT),
    ]
    print("SUMMARY:", " ".join(verdicts))
    return 0 if all(v == "PASS" for v in verdicts) else 1


if __name__ == "__main__":
    raise SystemExit(main())
