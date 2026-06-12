"""Build a 2_1 rename-variant from the real public dataset.

Simulates the platform's hidden-variant mutation surface for question 2_1:
the question text and the declared directory stay identical, but every csv
INSIDE the directory is renamed and its column headers get light synonym
rewrites (mixed zh/en). Evidence payloads (images/contracts/text) are copied
verbatim so the expected answer is exactly the public reference output.

Output: ./variant_renamed/   (regenerated from scratch on each run)

Stdlib only. PYTHONIOENCODING=utf-8 expected. ASCII-only prints.
"""
from __future__ import annotations

import csv
import io
import shutil
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
PUBLIC = REPO / "publish" / "publish_V1" / "采购数据清洗与汇总"
OUT = HERE / "variant_renamed"

# old filename -> (new filename, {old col -> new col}, output encoding)
CSV_PLAN = {
    "purchase_orders_raw.csv": (
        "po_data.csv",
        {
            "po_id": "po_no",
            "vendor_id": "supplier_id",
            "vendor_name_raw": "vendor_name",
            "category_code": "category_id",
            "business_purpose": "采购用途",
            "item_description": "item_desc",
            "amount_raw": "amount",
            "currency": "币种",
            "created_at": "create_date",
            "attachment_ids": "附件列表",
        },
        "utf-8",
    ),
    "queries.csv": (
        "询问.csv",
        {
            "query_id": "查询编号",
            "vendor_id": "供应商编码",
            "category_code": "品类编码",
            "year": "年份",
            "currency": "币种",
        },
        "gbk",  # also exercises the decode tolerance
    ),
    "vendors.csv": (
        "supplier_master.csv",
        {
            "vendor_id": "供应商编码",
            "legal_name": "公司名称",
            "tax_id": "统一社会信用代码",
            "business_scope": "经营范围",
            "brand_name": "品牌",
            "city": "城市",
        },
        "utf-8",
    ),
    "category_taxonomy.csv": (
        "品类目录.csv",
        {
            "category_code": "品类编码",
            "category_name": "品类名称",
            "definition": "定义",
            "boundary_note": "备注",
        },
        "utf-8",
    ),
    "attachment_manifest.csv": (
        "attach_list.csv",
        {
            "attachment_id": "附件编号",
            "po_id": "采购单号",
            "attachment_type": "附件类型",
            "file_path": "文件路径",
            "evidence_id": "证据编号",
        },
        "utf-8",
    ),
    "evidence_index.csv": (
        "证据索引.csv",
        {
            "evidence_id": "证据编号",
            "attachment_id": "附件编号",
            "attachment_type": "附件类型",
            "summary": "摘要",
        },
        "utf-8",
    ),
}

COPY_TREES = ("contracts", "images", "text_evidence")


def rewrite_csv(src: Path, column_map: dict) -> str:
    with open(src, "r", encoding="utf-8-sig", newline="") as handle:
        rows = list(csv.reader(handle))
    if rows:
        rows[0] = [column_map.get(col, col) for col in rows[0]]
    buffer = io.StringIO()
    csv.writer(buffer, lineterminator="\n").writerows(rows)
    return buffer.getvalue()


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    for old_name, (new_name, column_map, encoding) in CSV_PLAN.items():
        src = PUBLIC / old_name
        if not src.is_file():
            print("SKIP missing public csv:", old_name)
            continue
        text = rewrite_csv(src, column_map)
        (OUT / new_name).write_bytes(text.encode(encoding))
        print("csv  %-28s -> %s (%s)" % (old_name, new_name, encoding))

    for tree in COPY_TREES:
        src = PUBLIC / tree
        if src.is_dir():
            shutil.copytree(src, OUT / tree)
            print("tree %-28s -> copied verbatim" % tree)

    # data_rules.md is question prose, not data; copy as-is for completeness.
    rules = PUBLIC / "data_rules.md"
    if rules.is_file():
        shutil.copy(rules, OUT / "data_rules.md")

    print("variant written to", OUT)


if __name__ == "__main__":
    main()
