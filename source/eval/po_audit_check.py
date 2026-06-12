"""3_2 PO-compliance variant-validation harness.

Runs the po_compliance_audit skill against fixtures whose expected
non-compliant set is hand-verified, and reports PASS/FAIL with a diff.

The public fixture proves we did not regress the known-correct case; the
variant fixture (renamed vendors/people/products + rephrased approval wording
+ synonym statuses) proves the skill GENERALISES instead of pattern-matching
the public vocabulary. Under the platform's all-or-nothing grader a single
mismatched PO is a zero, so the bar here is an EXACT set match.

Usage:
    python -m source.eval.po_audit_check                 # both fixtures
    python -m source.eval.po_audit_check variant         # only the variant
    PO_AUDIT_USE_LLM=1 python -m source.eval.po_audit_check
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SKILL = ROOT / "source" / "solution" / "skills" / "po_compliance_audit" / "scripts" / "run.py"

# Expected non-compliant sets, hand-derived rule-by-rule (see fixture comments).
CASES = {
    "public": {
        "source_dir": ROOT / "publish" / "publish_V1" / "采购PO合规审计",
        "task_description": (
            "请审计 purchase_orders_raw.csv 中的全部 PO，金额达到或超过 50000 CNY 的进入深审，"
            "判断哪些 PO 不合规。输出逗号分隔升序 po_id。"
        ),
        "expected": [
            "PO-2026-0003", "PO-2026-0013", "PO-2026-0014", "PO-2026-0018",
            "PO-2026-0021", "PO-2026-0030", "PO-2026-0034", "PO-2026-0039",
            "PO-2026-0042",
        ],
    },
    "variant": {
        "source_dir": ROOT / "source" / "eval" / "fixtures" / "po_variant_A",
        "task_description": (
            "请审计 purchase_orders_raw.csv 中的全部 PO，金额达到或超过 50000 CNY 的进入深审，"
            "判断哪些 PO 不合规。输出逗号分隔升序 po_id。"
        ),
        # 03 scope / 04 partial / 05 director / 06 expired-VP /
        # 07 approval-after-po_date / 08 no-evidence / 09 not-covering
        "expected": [
            "PO-V-03", "PO-V-04", "PO-V-05", "PO-V-06", "PO-V-07",
            "PO-V-08", "PO-V-09",
        ],
    },
    "variantB": {
        "source_dir": ROOT / "source" / "eval" / "fixtures" / "po_variant_B",
        "task_description": (
            "请审计 purchase_orders_raw.csv 中的全部 PO，金额达到或超过 50000 CNY 的进入深审，"
            "判断哪些 PO 不合规。输出逗号分隔升序 po_id。"
        ),
        # 04 scope(laptop in office vendor) / 05 考虑一下 / 06 approves-other-PO /
        # 07 expired-VP / 08 director-only / 09 approval one day after po_date.
        # Compliant decoys: 01 amount==threshold & date==po_date & role"VP",
        # 02 role"副总裁" & status"settled", 03 role"Vice President".
        "expected": [
            "PO-B-04", "PO-B-05", "PO-B-06", "PO-B-07", "PO-B-08", "PO-B-09",
        ],
    },
}


def run_case(name: str, case: dict) -> bool:
    payload = json.dumps(
        {"source_dir": str(case["source_dir"]), "task_description": case["task_description"]},
        ensure_ascii=False,
    )
    proc = subprocess.run(
        [sys.executable, str(SKILL)],
        input=payload,
        text=True,
        capture_output=True,
        cwd=str(SKILL.parent),
        env=dict(os.environ),
    )
    raw = proc.stdout.strip()
    try:
        result = json.loads(raw)
    except ValueError:
        print(f"[{name}] FAIL — skill emitted non-JSON / crashed")
        print(f"  stdout: {raw[:400]!r}")
        print(f"  stderr: {proc.stderr.strip()[:400]!r}")
        return False

    got = [p for p in str(result.get("answer", "")).split(",") if p]
    expected = case["expected"]
    ok = got == expected
    print(f"[{name}] {'PASS' if ok else 'FAIL'}  ({'exact match' if ok else 'mismatch'})")
    if not ok:
        got_set, exp_set = set(got), set(expected)
        print(f"  expected: {','.join(expected)}")
        print(f"  got     : {','.join(got)}")
        if exp_set - got_set:
            print(f"  MISSED (false negatives): {sorted(exp_set - got_set)}")
        if got_set - exp_set:
            print(f"  EXTRA  (false positives): {sorted(got_set - exp_set)}")
    if result.get("warnings"):
        print(f"  warnings: {result['warnings']}")
    return ok


def main() -> None:
    which = sys.argv[1:] or ["public", "variant", "variantB"]
    results = {name: run_case(name, CASES[name]) for name in which if name in CASES}
    print("-" * 60)
    print("summary:", {k: ("PASS" if v else "FAIL") for k, v in results.items()})
    sys.exit(0 if all(results.values()) else 1)


if __name__ == "__main__":
    main()
