"""Verify the javac-primary path computes CORRECTLY on buggy variants.

The platform's real 2_3 is the public question text verbatim with a DIFFERENT
attached data file (different deduction + bracket table) and the same class
bugs. We synthesise that: take the public JavaSource_7_1 structure (which has a
complete buggy calculateTax), inject a fresh triple-base64 table + deduction,
build the matching worked-examples + ground-truth, then drive the REAL answer()
javac path and check the 10 hidden outputs equal that variant's ground truth.

We compare against the Python-extraction path for the same variant to show the
javac path is at least as good (and independent of the table-shape heuristics).

Usage:
  export JAVA_HOME=/d/environment/Java/jdk-21; export PATH="$JAVA_HOME/bin:$PATH"
  set -a; . ./.env.dashscope; set +a
  PYTHONIOENCODING=utf-8 python <this>

Stdlib only, ASCII-only prints.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RUN_PY = REPO / "source" / "solution" / "skills" / "java_tax_calculator" / "scripts" / "run.py"
PUBLIC_SRC = REPO / "publish" / "publish_V1" / "JavaSource_7_1.java"

STD_SALARIES = [5000, 12000, 25000, 35000, 55000, 60000, 80000, 90000, 150000, 500000]


def load_skill():
    spec = importlib.util.spec_from_file_location("jtr", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def triple_b64(text: str) -> str:
    raw = text.encode("utf-8")
    for _ in range(3):
        raw = base64.b64encode(raw)
    return raw.decode("ascii")


def truth_tax(salary, deduction, brackets):
    taxable = salary - deduction
    if taxable <= 0:
        return 0.0
    for lower, upper, rate, quick in brackets:
        if lower <= taxable <= upper:
            return taxable * rate - quick
    lower, upper, rate, quick = brackets[-1]
    return taxable * rate - quick


def make_variant_source(deduction, brackets):
    """Public structure (full buggy calculateTax) with swapped base64 data.

    The public getTaxBrackets() splits on "],[" and "," with NO spaces, so the
    payload must be COMPACT json exactly like the public constant.
    """
    text = PUBLIC_SRC.read_text(encoding="utf-8")
    rows = [[int(x) if float(x).is_integer() else x for x in row] for row in brackets]
    new_tax = triple_b64(json.dumps(rows, separators=(",", ":")))
    new_ded = triple_b64(str(int(deduction)))
    import re
    text = re.sub(r'TAX_BRACKETS_ENCODED\s*=\s*"[^"]+"',
                  'TAX_BRACKETS_ENCODED = "%s"' % new_tax, text)
    text = re.sub(r'DEDUCTION_POINT_ENCODED\s*=\s*"[^"]+"',
                  'DEDUCTION_POINT_ENCODED = "%s"' % new_ded, text)
    return text


def worked_examples(deduction, brackets):
    picks = [int(deduction) - 2000, int(deduction) + 1500, int(deduction) + 10000,
             int(deduction) + 40000, int(deduction) + 120000]
    out = []
    for s in picks:
        s = max(s, 0)
        out.append((s, "%.2f" % truth_tax(s, deduction, brackets)))
    return out


def task_text(examples):
    lines = ["附件是一份半成品Java源码（JavaSource_7_1.java）。", "", "【示例输入输出】"]
    for s, t in examples:
        lines.append("%d -> %s" % (s, t))
    lines += ["", "【隐藏用例】（以下输入按顺序执行，对应10个输出）"]
    lines += [str(s) for s in STD_SALARIES]
    return "\n".join(lines)


VARIANTS = [
    ("VA ded=5500 new-table", 5500.0, [
        [0, 3500, 0.03, 0], [3501, 13000, 0.11, 280], [13001, 28000, 0.19, 1320],
        [28001, 45000, 0.26, 3280], [45001, 70000, 0.32, 5980],
        [70001, 100000, 0.40, 11580], [100001, 999999999, 0.50, 21580],
    ]),
    ("VB ded=6000 new-table", 6000.0, [
        [0, 2000, 0.02, 0], [2001, 8000, 0.08, 120], [8001, 20000, 0.15, 680],
        [20001, 40000, 0.22, 2080], [40001, 70000, 0.28, 4180],
        [70001, 110000, 0.36, 9780], [110001, 999999999, 0.48, 23980],
    ]),
    ("VC ded=4000 fewer-brackets", 4000.0, [
        [0, 5000, 0.05, 0], [5001, 30000, 0.20, 750], [30001, 80000, 0.30, 3750],
        [80001, 999999999, 0.45, 15750],
    ]),
    # VD: fractional rates so taxes carry real cents -> exposes any integer
    # truncation in the model's repaired calculateTax.
    ("VD ded=5000 fractional", 5000.0, [
        [0, 3000, 0.035, 0], [3001, 12000, 0.105, 410], [12001, 25000, 0.205, 2660],
        [25001, 35000, 0.255, 4410], [35001, 55000, 0.305, 7160],
        [55001, 80000, 0.355, 15160], [80001, 999999999, 0.455, 15310],
    ]),
]


def run_variant(m, label, deduction, brackets):
    print("=" * 78)
    print("VARIANT:", label)
    source = make_variant_source(deduction, brackets)
    examples = worked_examples(deduction, brackets)
    desc = task_text(examples)
    truth = ["%.2f" % truth_tax(s, deduction, brackets) for s in STD_SALARIES]
    print("  ground-truth taxes:", truth)
    print("  worked-examples   :", examples)

    # write source to a scratch file the skill can resolve
    scratch = HERE / "_scratch"
    scratch.mkdir(exist_ok=True)
    src_path = scratch / "JavaSource_7_1.java"
    src_path.write_text(source, encoding="utf-8")

    args = {
        "task_description": desc,
        "source_file": str(src_path),
        "_runtime": {"allowed_file_paths": [str(src_path)]},
    }

    # --- javac primary ---
    os.environ.pop("JAVA_TAX_PREFER_JAVAC", None)
    t0 = time.monotonic()
    res_java = m.answer(args)
    wall_java = time.monotonic() - t0
    taxes_java = res_java["answer"].split(",")[1:]
    ok_java = taxes_java == truth

    # --- python extraction only (javac disabled) ---
    os.environ["JAVA_TAX_PREFER_JAVAC"] = "false"
    t0 = time.monotonic()
    res_py = m.answer(args)
    wall_py = time.monotonic() - t0
    os.environ.pop("JAVA_TAX_PREFER_JAVAC", None)
    taxes_py = res_py["answer"].split(",")[1:]
    ok_py = taxes_py == truth

    print("  [javac]  path=%-9s wall=%6.2fs 10/10=%s  %s"
          % (res_java["path"], wall_java, ok_java,
             "" if ok_java else "got=%s" % taxes_java))
    print("  [python] path=%-9s wall=%6.2fs 10/10=%s  %s"
          % (res_py["path"], wall_py, ok_py,
             "" if ok_py else "got=%s" % taxes_py))
    return dict(label=label, ok_java=ok_java, path_java=res_java["path"],
                wall_java=wall_java, ok_py=ok_py, path_py=res_py["path"])


def main():
    m = load_skill()
    print("model:", (m._model_config() or {}).get("model"))
    print("java available:", m.java_toolchain_available())
    print()
    results = [run_variant(m, *v) for v in VARIANTS]
    print("=" * 78)
    print("SUMMARY (javac primary should be 10/10 on every variant)")
    for r in results:
        print("  %-26s javac:%s(%s) python:%s(%s)"
              % (r["label"], r["ok_java"], r["path_java"], r["ok_py"], r["path_py"]))


if __name__ == "__main__":
    main()
