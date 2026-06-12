"""Content-based table discovery tests for purchase_clean_summary (task 2_1).

The platform variant renames the csv files inside the declared directory (the
question's `files` field only pins the directory name), which used to crash
resolve_source_dir's exact-name sentinel with exit 1 -> model-loop fallback.
These tests pin the new behaviour:

  - exact public filenames keep absolute priority (public set byte-identical);
  - renamed files + lightly renamed columns are discovered by header content;
  - the manifest degrades to empty instead of crashing when missing;
  - ambiguous / unidentifiable layouts still raise (router fallback), with the
    scanned headers in the error message for log forensics.

Offline: no model gateway, no OCR. Standard-library unittest.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT / "source" / "solution" / "skills" / "purchase_clean_summary" / "scripts" / "run.py"
)


def _load_module():
    spec = importlib.util.spec_from_file_location("purchase_discovery", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


INVOICE_TEXT = (
    "电子发票 PO 编号 PO-B 销售方 神州数据股份有限公司 "
    "统一社会信用代码 91110000BBBB 价税合计 CNY 20000"
)


def _write_exact_fixture(tmp: Path) -> Path:
    """Canonical public-style layout: exact filenames, canonical columns."""
    source = tmp / "purchase_exact"
    source.mkdir()
    (source / "purchase_orders_raw.csv").write_text(
        "po_id,vendor_id,vendor_name_raw,category_code,business_purpose,item_description,"
        "amount_raw,currency,created_at,attachment_ids\n"
        "PO-A,V100,联创科技,COMPUTE_SERVICE,GPU 算力,推理节点,10000,CNY,2026-04-01,\n"
        "PO-B,V200,神州数据,DATA_GOVERNANCE,数据血缘,主数据平台,20000,CNY,2026-04-02,ATT1\n",
        encoding="utf-8",
    )
    (source / "queries.csv").write_text(
        "query_id,vendor_id,category_code,year,currency\n"
        "Q1,V100,COMPUTE_SERVICE,2026,CNY\n"
        "Q2,V200,DATA_GOVERNANCE,2026,CNY\n"
        "Q3,V100,DATA_GOVERNANCE,2026,CNY\n",
        encoding="utf-8",
    )
    (source / "vendors.csv").write_text(
        "vendor_id,legal_name,brand_name,tax_id\n"
        "V100,联创科技有限公司,联创科技,91110000AAAA\n"
        "V200,神州数据股份有限公司,神州数据,91110000BBBB\n",
        encoding="utf-8",
    )
    (source / "category_taxonomy.csv").write_text(
        "category_code,category_name\n"
        "COMPUTE_SERVICE,算力服务\n"
        "DATA_GOVERNANCE,数据治理\n",
        encoding="utf-8",
    )
    (source / "attachment_manifest.csv").write_text(
        "attachment_id,po_id,attachment_type,file_path,evidence_id\n"
        "ATT1,PO-B,invoice,attachments/att1.txt,EV1\n",
        encoding="utf-8",
    )
    attachments = source / "attachments"
    attachments.mkdir()
    (attachments / "att1.txt").write_text(INVOICE_TEXT, encoding="utf-8")
    return source


def _write_renamed_fixture(tmp: Path, *, drop_attachment_column: bool = False) -> Path:
    """Same data, variant shape: renamed csv files + synonym column headers.
    queries csv is written in GBK to exercise the decode tolerance."""
    source = tmp / "purchase_variant"
    source.mkdir()
    attachment_header = "" if drop_attachment_column else ",附件列表"
    attachment_cell_a = "" if drop_attachment_column else ","
    attachment_cell_b = "" if drop_attachment_column else ",ATT1"
    amount_b = "" if drop_attachment_column else "20000"
    (source / "po_data.csv").write_text(
        "po_no,supplier_id,vendor_name,category_id,采购用途,item_desc,amount,币种,create_date"
        + attachment_header + "\n"
        + "PO-A,V100,联创科技,COMPUTE_SERVICE,GPU 算力,推理节点,10000,CNY,2026-04-01" + attachment_cell_a + "\n"
        + "PO-B,V200,神州数据,DATA_GOVERNANCE,数据血缘,主数据平台," + amount_b + ",CNY,2026-04-02" + attachment_cell_b + "\n",
        encoding="utf-8",
    )
    (source / "询问.csv").write_bytes(
        (
            "查询编号,供应商编码,品类编码,年份,币种\n"
            "Q1,V100,COMPUTE_SERVICE,2026,CNY\n"
            "Q2,V200,DATA_GOVERNANCE,2026,CNY\n"
            "Q3,V100,DATA_GOVERNANCE,2026,CNY\n"
        ).encode("gbk")
    )
    (source / "supplier_master.csv").write_text(
        "供应商编码,公司名称,品牌,统一社会信用代码\n"
        "V100,联创科技有限公司,联创科技,91110000AAAA\n"
        "V200,神州数据股份有限公司,神州数据,91110000BBBB\n",
        encoding="utf-8",
    )
    (source / "品类目录.csv").write_text(
        "品类编码,品类名称\n"
        "COMPUTE_SERVICE,算力服务\n"
        "DATA_GOVERNANCE,数据治理\n",
        encoding="utf-8",
    )
    (source / "attach_list.csv").write_text(
        "附件编号,采购单号,附件类型,文件路径,证据编号\n"
        "ATT1,PO-B,invoice,attachments/att1.txt,EV1\n",
        encoding="utf-8",
    )
    attachments = source / "attachments"
    attachments.mkdir()
    (attachments / "att1.txt").write_text(INVOICE_TEXT, encoding="utf-8")
    return source


class TableDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        self.module = _load_module()
        # Offline: never let the rescue pass try the gateway.
        self.module._model_config = lambda: None

    def _answer(self, source: Path):
        return self.module.answer(
            {
                "task_description": "清洗规则",
                "source_dir": str(source),
                "do_ocr": False,
                "_runtime": {},
            }
        )

    def test_exact_name_fixture_baseline(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_exact_fixture(Path(tmp))
            result = self._answer(source)
        self.assertEqual(result["answer"], "10000,20000,0")

    def test_renamed_files_and_columns_same_answer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_renamed_fixture(Path(tmp))
            result = self._answer(source)
        self.assertEqual(result["answer"], "10000,20000,0")

    def test_exact_names_win_over_decoys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_exact_fixture(Path(tmp))
            # Drop a PO-shaped decoy with different data next to the real file.
            (source / "po_data.csv").write_text(
                "po_no,supplier_id,amount,币种\nPO-X,V100,99999,CNY\n",
                encoding="utf-8",
            )
            _, tables, _ = self.module.resolve_source_tables(str(source), {})
            self.assertEqual(
                Path(tables[self.module.TABLE_PO]).name, "purchase_orders_raw.csv"
            )
            self.assertEqual(Path(tables[self.module.TABLE_QUERIES]).name, "queries.csv")
            result = self._answer(source)
        self.assertEqual(result["answer"], "10000,20000,0")

    def test_partial_rename_fills_missing_roles(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_exact_fixture(Path(tmp))
            (source / "queries.csv").rename(source / "询问.csv")
            _, tables, _ = self.module.resolve_source_tables(str(source), {})
            self.assertEqual(Path(tables[self.module.TABLE_QUERIES]).name, "询问.csv")
            result = self._answer(source)
        self.assertEqual(result["answer"], "10000,20000,0")

    def test_manifest_missing_degrades_to_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_exact_fixture(Path(tmp))
            (source / "attachment_manifest.csv").unlink()
            result = self._answer(source)
        # PO-B still counts from its complete systematic fields.
        self.assertEqual(result["answer"], "10000,20000,0")

    def test_attachment_column_missing_uses_manifest_po_join(self) -> None:
        # PO-B has no amount and the PO table has no attachment-id column at
        # all; only the manifest's po_id join can reach the invoice that
        # supplies the amount. Without the join the answer would be 10000,0,0.
        with tempfile.TemporaryDirectory() as tmp:
            source = _write_renamed_fixture(Path(tmp), drop_attachment_column=True)
            result = self._answer(source)
        self.assertEqual(result["answer"], "10000,20000,0")

    def test_nothing_found_raises_with_scan_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "empty_case"
            source.mkdir()
            (source / "unrelated.csv").write_text("a,b,c\n1,2,3\n", encoding="utf-8")
            with self.assertRaises(FileNotFoundError) as ctx:
                self._answer(source)
        message = str(ctx.exception)
        self.assertIn("unrelated.csv", message)
        self.assertIn("a|b|c", message)

    def test_ambiguous_po_candidates_abstain(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "ambiguous"
            source.mkdir()
            row = "po_no,supplier_id,amount,币种\nPO-X,V100,1,CNY\n"
            (source / "po_first.csv").write_text(row, encoding="utf-8")
            (source / "po_second.csv").write_text(row, encoding="utf-8")
            with self.assertRaises(FileNotFoundError) as ctx:
                self._answer(source)
        # Abstaining must still leave forensics: every scanned csv + headers.
        message = str(ctx.exception)
        self.assertIn("po_first.csv", message)
        self.assertIn("po_second.csv", message)
        self.assertIn("po_no", message)


if __name__ == "__main__":
    unittest.main()
