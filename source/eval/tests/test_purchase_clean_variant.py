"""Variant-robustness closed loop for purchase_clean_summary (2_1 / 题目5).

The platform runs a HIDDEN variant: same question text, different attachment
data — and historically also renamed csv files, reworded column headers and
rephrased evidence. This test rebuilds a fully independent dataset that mutates
all of those axes at once and asserts the deterministic answer, so a future
edit that overfits the public set fails here instead of on the leaderboard.

Runs offline (do_ocr=False, text evidence only) so it is deterministic and
needs no model gateway.
"""
from __future__ import annotations

import os
from pathlib import Path

from source.solution.skills.purchase_clean_summary.scripts import run as R


# Renamed files + REWORDED headers (alias maps must still classify each table).
PO_CSV = "po_records.csv"
QUERY_CSV = "query_list.csv"
VENDOR_CSV = "supplier_master.csv"
TAX_CSV = "cat_def.csv"
MANIFEST_CSV = "att_manifest.csv"

VENDORS = [
    # 供应商编码,法定名称,统一社会信用代码,经营范围,品牌,城市
    ("S001", "朗辰算力科技有限公司", "91110108MA01Z0001A", "模型评测算力、GPU推理、临时云资源", "Langchen Compute", "北京"),
    ("S002", "朗辰咨询服务有限公司", "91110108MA01Z0002B", "AI治理咨询、制度设计、管理咨询", "Langchen Advisory", "北京"),
    ("S003", "朗辰安全技术有限公司", "91310115MA02Z0003C", "红队演练、漏洞扫描、渗透测试", "Langchen Security", "上海"),
    ("S004", "维度数据治理有限公司", "91440101MA5Z0004D", "数据血缘、标签治理、主数据清洗", "Weidu Data", "广州"),
    ("S005", "维度云软件有限公司", "91440101MA5Z0005E", "SaaS订阅、监控平台、API订阅", "Weidu SaaS", "广州"),
]

TAXONOMY = [
    ("COMPUTE_SERVICE", "算力与云资源服务", "GPU 算力、推理、压测云资源", "不含软件订阅或硬件"),
    ("AI_CONSULTING", "咨询与治理服务", "管理咨询、AI 治理、制度设计、培训工作坊", "不含数据清洗或软件订阅"),
    ("DATA_GOVERNANCE", "数据治理服务", "数据血缘、标签治理、主数据清洗、数据目录", "不含 AI 咨询或软件订阅"),
    ("SOFTWARE_SUBSCRIPTION", "软件订阅与 SaaS", "监控平台、API 调用、云软件账号订阅", "不含 GPU 裸资源或咨询"),
]

QUERIES = [
    ("R1", "S001", "COMPUTE_SERVICE", "2026", "CNY"),
    ("R2", "S002", "AI_CONSULTING", "2026", "CNY"),
    ("R3", "S004", "DATA_GOVERNANCE", "2026", "CNY"),
    ("R4", "S005", "SOFTWARE_SUBSCRIPTION", "2026", "CNY"),
]

# po_id, vendor_id, vendor_name_raw, category, purpose, item, amount, currency, att_ids
POS = [
    ("PV-001", "S001", "朗辰算力科技有限公司", "COMPUTE_SERVICE", "推理回放", "推理节点", "10000", "CNY", ""),
    ("PV-002", "S001", "Langchen Compute", "COMPUTE_SERVICE", "压测资源", "压测资源", "5000", "CNY", "A1"),   # invoice confirms 5000
    ("PV-003", "S001", "朗辰算力科技", "COMPUTE_SERVICE", "模型评测", "GPU 池", "", "CNY", "A2"),              # amount filled from invoice 7000
    ("PV-004", "S002", "朗辰咨询服务有限公司", "AI_CONSULTING", "制度设计", "工作坊", "20000", "CNY", ""),
    ("PV-005", "", "朗辰", "AI_CONSULTING", "AI治理", "合规咨询", "8000", "CNY", "A3"),                        # vendor from contract -> S002
    ("PV-006", "S002", "朗辰咨询服务", "AI_CONSULTING", "模型风险", "评估", "30000", "", "A4"),                # currency empty, invoice confirms CNY
    ("PV-007", "S004", "维度数据治理有限公司", "DATA_GOVERNANCE", "数据血缘", "血缘修复", "15000", "CNY", ""),
    ("PV-008", "S004", "维度数据治理", "", "标签治理", "标签治理", "6000", "CNY", "A5"),                       # category from contract scope
    ("PV-009", "S005", "维度云软件有限公司", "SOFTWARE_SUBSCRIPTION", "订阅", "监控平台", "9000", "CNY", "A6"),  # invoice USD -> drop
    ("PV-010", "S005", "Weidu SaaS", "SOFTWARE_SUBSCRIPTION", "订阅", "API 调用", "12000", "CNY", "A7"),       # invoice 11000 < system -> drop
    ("PV-011", "S005", "维度云软件有限公司", "SOFTWARE_SUBSCRIPTION", "年费", "账号", "4000", "CNY", ""),
    ("PV-012", "S005", "维度云软件有限公司", "SOFTWARE_SUBSCRIPTION", "订阅", "账号", "", "CNY", "A8"),         # invoice wrong-PO -> no fill -> drop
]

# attachment_id -> (po_id, type, relative file path under evidence/)
MANIFEST = {
    "A1": ("PV-002", "invoice", "evidence/A1.txt"),
    "A2": ("PV-003", "invoice", "evidence/A2.txt"),
    "A3": ("PV-005", "contract_excerpt", "evidence/A3.txt"),
    "A4": ("PV-006", "invoice", "evidence/A4.txt"),
    "A5": ("PV-008", "contract_excerpt", "evidence/A5.txt"),
    "A6": ("PV-009", "invoice", "evidence/A6.txt"),
    "A7": ("PV-010", "invoice", "evidence/A7.txt"),
    "A8": ("PV-012", "invoice", "evidence/A8.txt"),
}

# Evidence bodies. Deliberately mix layouts: A2/A4 use OCR-style newline labels
# WITHOUT colons; A6/A7 are tab-separated; the rest use the public-set colon
# style. The seller/tax/currency/amount extraction must survive all of them.
EVIDENCE = {
    "A1": (
        "发票号码：INV-A1\n关联 PO：PV-002\n发票状态：正常\n"
        "销售方：朗辰算力科技有限公司\n销售方税号：91110108MA01Z0001A\n价税合计：CNY 5000"
    ),
    "A2": (  # OCR newline style, amount fill to 7000
        "增值税电子发票\nPO 编号\nPV-003\n销售方\n朗辰算力科技有限公司\n"
        "统一社会信用代码\n91110108MA01Z0001A\n价税合计\nCNY 7000"
    ),
    "A3": (
        "合同编号：CT-A3\n关联 PO：PV-005\n相对方：朗辰咨询服务有限公司\n"
        "服务范围：AI 治理制度工作坊；模型风险评估；合规流程设计"
    ),
    "A4": (  # OCR newline style, currency confirm CNY
        "增值税电子发票\nPO 编号\nPV-006\n发票状态\n正常\n销售方\n朗辰咨询服务有限公司\n"
        "统一社会信用代码\n91110108MA01Z0002B\n价税合计\nCNY 30000"
    ),
    "A5": (
        "合同编号：CT-A5\n关联 PO：PV-008\n相对方：维度数据治理有限公司\n"
        "服务范围：数据血缘修复；标签治理；主数据清洗；数据目录整理"
    ),
    "A6": (  # tab-separated, USD trap
        "增值税电子发票\nPO 编号\tPV-009\n发票状态\t正常\n销售方\t维度云软件有限公司\n"
        "统一社会信用代码\t91440101MA5Z0005E\n价税合计\tUSD 9000"
    ),
    "A7": (  # tab-separated, invoice amount < system 12000
        "增值税电子发票\nPO 编号\tPV-010\n发票状态\t正常\n销售方\t维度云软件有限公司\n"
        "统一社会信用代码\t91440101MA5Z0005E\n价税合计\tCNY 11000"
    ),
    "A8": (  # wrong-PO invoice (id mismatch) -> cannot fill PV-012's empty amount
        "发票号码：INV-A8\n关联 PO：PV-999\n发票状态：正常\n"
        "销售方：维度云软件有限公司\n销售方税号：91440101MA5Z0005E\n价税合计：CNY 13000\n"
        "该附件 PO 编号与当前采购记录不一致，不能用于当前记录。"
    ),
}

EXPECTED = "22000,58000,21000,4000"


def _write_csv(path: Path, header: list[str], rows: list[tuple]) -> None:
    lines = [",".join(header)]
    for row in rows:
        lines.append(",".join(str(cell) for cell in row))
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build(root: Path) -> None:
    _write_csv(
        root / PO_CSV,
        ["采购单号", "供应商编码", "录入供应商", "品类代码", "业务用途", "采购描述", "录入金额", "货币", "附件id"],
        POS,
    )
    _write_csv(root / QUERY_CSV, ["查询编号", "供应商编码", "品类代码", "年份", "货币"], QUERIES)
    _write_csv(root / VENDOR_CSV, ["供应商编码", "法定名称", "统一社会信用代码", "经营范围", "品牌", "城市"], VENDORS)
    _write_csv(root / TAX_CSV, ["品类代码", "品类名称", "定义", "边界说明"], TAXONOMY)
    _write_csv(
        root / MANIFEST_CSV,
        ["附件id", "采购单号", "类型", "文件路径"],
        [(aid, po, kind, path) for aid, (po, kind, path) in MANIFEST.items()],
    )
    ev = root / "evidence"
    ev.mkdir(exist_ok=True)
    for aid, body in EVIDENCE.items():
        (ev / f"{aid}.txt").write_text(body, encoding="utf-8")


def test_purchase_clean_variant_offline(tmp_path) -> None:
    _build(tmp_path)
    out = R.answer(
        {"source_dir": str(tmp_path), "task_description": "采购数据清洗与汇总", "do_ocr": False},
        ocr_reader=lambda _path: "",
    )
    assert out["answer"] == EXPECTED, (
        f"variant answer drifted: got {out['answer']} want {EXPECTED}; "
        f"included={sorted(out.get('included', []))}"
    )


def test_variant_tables_discovered_by_header() -> None:
    """The renamed csvs must each be classified to the right table role."""
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        _build(root)
        _src, tables, _sniffed = R.resolve_source_tables(str(root), {})
        assert os.path.basename(tables[R.TABLE_PO]) == PO_CSV
        assert os.path.basename(tables[R.TABLE_QUERIES]) == QUERY_CSV
        assert os.path.basename(tables[R.TABLE_VENDORS]) == VENDOR_CSV
        assert os.path.basename(tables[R.TABLE_TAXONOMY]) == TAX_CSV
        assert os.path.basename(tables[R.TABLE_MANIFEST]) == MANIFEST_CSV
