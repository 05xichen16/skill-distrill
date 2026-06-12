"""End-to-end verification of the javac-primary java_tax_calculator skill.

Drives the REAL answer() with the REAL DashScope 35B model + REAL JDK21 and
records: which path was taken, repair rounds, total wall clock, and whether the
11-segment answer matches the public reference exactly. Also exercises the
"time is nearly up" fallback by shrinking SKILL_BUDGET_SECONDS.

Usage:
  export JAVA_HOME=/d/environment/Java/jdk-21; export PATH="$JAVA_HOME/bin:$PATH"
  set -a; . ./.env.dashscope; set +a
  PYTHONIOENCODING=utf-8 python <this>

Stdlib only, ASCII-only prints.
"""
from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RUN_PY = REPO / "source" / "solution" / "skills" / "java_tax_calculator" / "scripts" / "run.py"
PUBLIC_SRC = REPO / "publish" / "publish_V1" / "JavaSource_7_1.java"

TASK_TEXT = (PUBLIC_SRC.read_text(encoding="utf-8"))  # placeholder, replaced below

TASK_DESCRIPTION = """附件是一份半成品Java源码（JavaSource_7_1.java）。

【示例输入输出】
3000 -> 0.00
8000 -> 90.00
15000 -> 590.00
30000 -> 2340.00
100000 -> 27440.00

【隐藏用例】（以下输入按顺序执行，对应10个输出）
5000
12000
25000
35000
55000
60000
80000
90000
150000
500000
"""

REFERENCE_TAXES = ["0.00", "290.00", "1340.00", "3090.00", "7840.00",
                   "9340.00", "11090.00", "22940.00", "49940.00", "207440.00"]


def load_skill():
    spec = importlib.util.spec_from_file_location("jtr", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def run_case(m, label, env_overrides):
    saved = {}
    for k, v in env_overrides.items():
        saved[k] = os.environ.get(k)
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v
    repair_calls = {"n": 0}
    orig_repair = m.llm_repair_source

    def counting_repair(config, source, feedback, timeout):
        repair_calls["n"] += 1
        t0 = time.monotonic()
        out = orig_repair(config, source, feedback, timeout)
        print("    repair round %d: %.2fs usable=%s"
              % (repair_calls["n"], time.monotonic() - t0, out is not None))
        return out

    m.llm_repair_source = counting_repair
    print("=" * 78)
    print("CASE:", label)
    t0 = time.monotonic()
    try:
        result = m.answer({
            "task_description": TASK_DESCRIPTION,
            "source_file": str(PUBLIC_SRC),
            "_runtime": {"allowed_file_paths": [str(PUBLIC_SRC)]},
        })
    finally:
        m.llm_repair_source = orig_repair
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v
    total = time.monotonic() - t0
    segs = result["answer"].split(",")
    taxes = segs[1:]
    version_ok = "21.0.11" in segs[0]
    taxes_ok = taxes == REFERENCE_TAXES
    correct = sum(1 for a, b in zip(taxes, REFERENCE_TAXES) if a == b)
    print("  path=%s rounds=%d wall=%.2fs n_segments=%d"
          % (result["path"], repair_calls["n"], total, len(segs)))
    print("  version_segment=%r (contains 21.0.11=%s)" % (segs[0], version_ok))
    print("  taxes 10/10 exact=%s (%d/10 correct)" % (taxes_ok, correct))
    if not taxes_ok:
        print("  got     :", taxes)
        print("  expected:", REFERENCE_TAXES)
    print("  warnings:", result.get("warnings"))
    return dict(label=label, path=result["path"], rounds=repair_calls["n"],
                wall=total, version_ok=version_ok, taxes_ok=taxes_ok,
                correct=correct, segs=len(segs))


def main():
    m = load_skill()
    print("model:", (m._model_config() or {}).get("model"))
    print("java_toolchain_available:", m.java_toolchain_available())
    print("java_version_line():", repr(m.java_version_line()))
    print()

    results = []
    # 1) Default config: javac primary, real model, real JDK.
    results.append(run_case(m, "DEFAULT (javac primary)", {
        "JAVA_TAX_PREFER_JAVAC": None,  # default True
    }))
    # 2) Time nearly up: tiny budget must skip javac and fall back fast,
    #    still emitting a legal 11-segment answer (version + python/shape).
    results.append(run_case(m, "TINY BUDGET (deadline forces fallback)", {
        "SKILL_BUDGET_SECONDS": "20",
    }))
    # 3) javac disabled: python extraction primary (the old behaviour).
    results.append(run_case(m, "JAVAC DISABLED (python extraction primary)", {
        "JAVA_TAX_PREFER_JAVAC": "false",
    }))

    print("=" * 78)
    print("SUMMARY")
    for r in results:
        print("  %-42s path=%-10s rounds=%d wall=%6.2fs ver=%s taxes10/10=%s segs=%d"
              % (r["label"][:42], r["path"], r["rounds"], r["wall"],
                 r["version_ok"], r["taxes_ok"], r["segs"]))


if __name__ == "__main__":
    main()
