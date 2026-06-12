"""Public-set ground-truth lock for purchase_clean_summary (2_1 / 题目5).

Runs the deterministic algorithm on the REAL public dataset with a stub OCR
that returns the hand-transcribed image-attachment texts, so the full 12/12
answer (incl. the USD / amount-below-system / wrong-PO / category-correction
traps) is pinned offline, decoupled from live OCR quality. Pairs with
test_purchase_clean_variant.py (independent variant data) to form the variant
validation loop that was historically missing for this question.
"""
from __future__ import annotations

import os

import pytest

from source.solution.skills.purchase_clean_summary.scripts import run as R

ROOT = os.path.dirname(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
)
PUB = os.path.join(ROOT, "publish", "publish_V1", "采购数据清洗与汇总")

# image basename -> transcription (formatted like the text-evidence files)
IMG_TEXT = {
    "ATT-00002.png": (  # PO-5 invoice, CNY 11233, V0007
        "电子发票 No. INV-00002\n增值税电子发票\n"
        "PO 编号：PO-2026-00005\n购买方：北京星云智能科技有限公司\n"
        "销售方：云杉云软件有限公司\n统一社会信用代码：91440101MA5D0098P\n"
        "项目名称：监控平台年费\n价税合计：CNY 11233\n税额：635.83\n"
        "发票可用于核验金额、币种、销售方法定名称和统一社会信用代码。"
    ),
    "ATT-00003.png": (  # PO-13 invoice, CNY 28893, V0001
        "电子发票 No. INV-00003\n增值税电子发票\n"
        "PO 编号：PO-2026-00013\n购买方：北京星云智能科技有限公司\n"
        "销售方：星河算力科技有限公司\n统一社会信用代码：91110108MA01X0012A\n"
        "项目名称：模型评测 GPU 池\n价税合计：CNY 28893\n税额：1635.45"
    ),
    "ATT-00016.png": (  # PO-24 invoice, CNY 55737 (< system 58180 -> drop)
        "电子发票 No. INV-00016\n增值税电子发票\n"
        "PO 编号：PO-2026-00024\n购买方：北京星云智能科技有限公司\n"
        "销售方：启衡智能设备有限公司\n统一社会信用代码：91120116MA03H0099T\n"
        "项目名称：打印耗材\n价税合计：CNY 55737\n税额：3154.92\n"
        "发票金额低于系统金额；没有其他合法结算凭证时，该 PO 不计入。"
    ),
    "ATT-00018.png": (  # PO-17 invoice, USD 29355 -> drop
        "电子发票 No. INV-00018\n增值税电子发票\n"
        "PO 编号：PO-2026-00017\n购买方：北京星云智能科技有限公司\n"
        "销售方：云杉云软件有限公司\n统一社会信用代码：91440101MA5D0098P\n"
        "项目名称：监控平台年费\n价税合计：USD 29355\n税额：1661.6\n"
        "发票币种不是 CNY；本题不做汇率换算。"
    ),
    "ATT-00023.png": (  # PO-40 invoice but wrong PO id -> invalid
        "电子发票 No. INV-00023\n增值税电子发票\n"
        "PO 编号：PO-2026-X107\n购买方：北京星云智能科技有限公司\n"
        "销售方：云桥会议服务有限公司\n统一社会信用代码：9100000000000221732\n"
        "项目名称：AI 治理制度工作坊\n价税合计：CNY 44667\n税额：2528.32\n"
        "该附件 PO 编号与当前采购记录不一致，不能用于当前记录。"
    ),
    "ATT-00004.png": (  # PO-22 contract -> V0012 TRAVEL_EVENT
        "合同服务范围页 CT-00004\n采购合同节选\n"
        "PO 编号：PO-2026-00022\n项目编码：PRJ-TRA-2026-025\n"
        "合同相对方：远岚会议服务有限公司\n"
        "服务范围：会议场地；酒店安排；交通接驳；现场活动执行\n"
        "合同期间：2026-01-01 至 2026-12-31"
    ),
    "ATT-00024.png": (  # PO-44 price comparison (clue only); PO is USD anyway
        "比价/询价记录 IMG-CMP-00024\n采购比价记录\n"
        "PO 编号：PO-2026-00044\n项目编码：PRJ-AI-2026-061\n"
        "海岳智能设备有限公司 报价：CNY 19786\n候选供应商 A 报价：CNY 21186\n"
        "候选供应商 B 报价：CNY 17786\n报价/比价记录不是付款金额凭证，不能覆盖系统金额或发票金额。"
    ),
    "ATT-00001.png": "采购专项沟通群\nPO 编号：PO-2026-00003\n录入供应商：北辰安全技术\n录入金额：13704 CNY\n用途是红队演练，聊天记录只作线索。",
    "ATT-00020.png": "采购专项沟通群\nPO 编号：PO-2026-00036\n录入供应商：启明\n录入金额：62274 CNY\n用途是数据血缘修复，聊天记录只作线索。",
    "ATT-00021.png": "采购专项沟通群\nPO 编号：PO-2026-00024\n录入供应商：启衡智能设备\n录入金额：58180 CNY\n用途是打印耗材，聊天记录只作线索。",
    "ATT-00022.png": "采购专项沟通群\nPO 编号：PO-2026-00017\n录入供应商：Spruce SaaS\n录入金额：29355 CNY\n用途是监控平台年费，聊天记录只作线索。",
    "ATT-00025.png": "采购专项沟通群\nPO 编号：PO-2026-00045\n录入供应商：星火算力科技\n录入金额：大概 16397 左右\n用途是监控平台年费，聊天记录只作线索。",
}


def stub_ocr(path: str) -> str:
    return IMG_TEXT.get(os.path.basename(path), "")


# Hand-computed and independently confirmed by the deterministic algorithm.
GROUND_TRUTH = "122377,128945,97826,104474,60723,150997,176952,161401,120853,26393,118404,99654"


@pytest.mark.skipif(not os.path.isdir(PUB), reason="public dataset not present")
def test_purchase_clean_public_set_full_marks() -> None:
    rules = R.read_text(os.path.join(PUB, "data_rules.md"))
    out = R.answer(
        {"source_dir": PUB, "task_description": rules, "do_ocr": True},
        ocr_reader=stub_ocr,
    )
    assert out["answer"] == GROUND_TRUTH, (
        f"public-set answer drifted: got {out['answer']} want {GROUND_TRUTH}; "
        f"included={sorted(out.get('included', []))}"
    )


@pytest.mark.skipif(not os.path.isdir(PUB), reason="public dataset not present")
def test_purchase_clean_public_no_ocr_degrades_without_crash() -> None:
    """With OCR unavailable the run must NOT crash; it degrades to a well-formed
    12-int answer, wrong only on the two image-OCR-dependent traps (Q5 USD,
    Q12 invoice<system). This is the 0/9 -> ~7.5/9 platform floor."""
    rules = R.read_text(os.path.join(PUB, "data_rules.md"))

    def boom(_path: str) -> str:
        raise ConnectionError("simulated gateway storm")

    out = R.answer(
        {"source_dir": PUB, "task_description": rules, "do_ocr": True},
        ocr_reader=boom,
    )
    segments = out["answer"].split(",")
    assert len(segments) == 12 and all(s.lstrip("-").isdigit() for s in segments)
    truth = GROUND_TRUTH.split(",")
    correct = sum(a == b for a, b in zip(segments, truth))
    assert correct == 10, f"degraded score changed: {correct}/12 ({out['answer']})"
