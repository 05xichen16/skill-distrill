"""Pure-Python (no gateway) driver for 2_3 variant diagnosis.

For each variant we:
  1. Define the variant's GROUND-TRUTH (deduction + bracket table) and compute
     the 10 standard-salary tax outputs by hand (reference for that variant).
  2. Pick worked-examples the variant's true table reproduces (mirrors what the
     hidden question text would supply: salary -> tax).
  3. Feed the variant SOURCE + those examples into the skill's pure code path
     exactly as answer() does with config=None (no model), and report:
       - candidates found?
       - any candidate validates against the examples?
       - the 10 outputs the skill would emit (validated path)
       - what answer() would actually submit (validated / shape-fallback / 0.00)

Stdlib only. PYTHONIOENCODING=utf-8 expected. ASCII-only prints.
"""
from __future__ import annotations

import base64
import importlib.util
import json
import os
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[4]
RUN_PY = REPO / "source" / "solution" / "skills" / "java_tax_calculator" / "scripts" / "run.py"

STD_SALARIES = [5000, 12000, 25000, 35000, 55000, 60000, 80000, 90000, 150000, 500000]


def load_skill():
    spec = importlib.util.spec_from_file_location("jtr", RUN_PY)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def truth_tax(salary, deduction, brackets):
    """Reference calc for a variant's GROUND TRUTH (same formula the grader uses)."""
    taxable = salary - deduction
    if taxable <= 0:
        return 0.0
    for lower, upper, rate, quick in brackets:
        if lower <= taxable <= upper:
            return taxable * rate - quick
    lower, upper, rate, quick = brackets[-1]
    return taxable * rate - quick


def triple_b64(text: str) -> str:
    raw = text.encode("utf-8")
    for _ in range(3):
        raw = base64.b64encode(raw)
    return raw.decode("ascii")


def fmt(vals):
    return ["%.2f" % v for v in vals]


# ----- variant ground-truth tables (lower, upper, rate, quick) -----------------

# V1: public values, table only in prose comments, no base64.
V1 = dict(
    ded=5000.0,
    brackets=[
        [0, 3000, 0.03, 0],
        [3001, 12000, 0.10, 410],
        [12001, 25000, 0.20, 2660],
        [25001, 35000, 0.25, 4410],
        [35001, 55000, 0.30, 7160],
        [55001, 80000, 0.35, 15160],
        [80001, 999999999, 0.45, 15310],
    ],
)

# V2: parallel arrays, deduction 6000, brand-new bracket values.
# upper = {2000,8000,20000,40000,70000,110000,inf}; rate% = {2,8,15,22,28,36,48}
# quick = {0,120,680,2080,4180,9780,23980}; lower = prev_upper+1.
V2 = dict(
    ded=6000.0,
    brackets=[
        [0, 2000, 0.02, 0],
        [2001, 8000, 0.08, 120],
        [8001, 20000, 0.15, 680],
        [20001, 40000, 0.22, 2080],
        [40001, 70000, 0.28, 4180],
        [70001, 110000, 0.36, 9780],
        [110001, 999999999, 0.48, 23980],
    ],
)

# V3: public STRUCTURE + real base64, deduction 5500, new bracket values.
# upper = {3500,13000,28000,45000,70000,100000,inf}; rate = {3,11,19,26,32,40,50}
# quick computed for continuity: q1=0; q_{i}=q_{i-1}+upper_{i-1}*(rate_i-rate_{i-1})
V3 = dict(
    ded=5500.0,
    brackets=[
        [0, 3500, 0.03, 0],
        [3501, 13000, 0.11, 280],
        [13001, 28000, 0.19, 1320],
        [28001, 45000, 0.26, 3280],
        [45001, 70000, 0.32, 5980],
        [70001, 100000, 0.40, 11580],
        [100001, 999999999, 0.50, 21580],
    ],
)

# V4: 2d literal [upper, rate%, quick], deduction 5000, new values.
# upper = {4000,15000,30000,45000,65000,95000,inf}; rate% = {4,12,22,28,33,38,50}
# quick = {0,320,1820,3620,5870,9120,20520}; lower = prev_upper+1.
V4 = dict(
    ded=5000.0,
    brackets=[
        [0, 4000, 0.04, 0],
        [4001, 15000, 0.12, 320],
        [15001, 30000, 0.22, 1820],
        [30001, 45000, 0.28, 3620],
        [45001, 65000, 0.33, 5870],
        [65001, 95000, 0.38, 9120],
        [95001, 999999999, 0.50, 20520],
    ],
)


def worked_examples(spec):
    """Pick 5 salaries that exercise distinct brackets; return [(salary, '%.2f')]."""
    ded = spec["ded"]
    picks = [
        int(ded) - 2000,            # below threshold -> 0
        int(ded) + 1500,            # bracket 1
        int(ded) + 10000,           # mid bracket
        int(ded) + 30000,           # higher bracket
        int(ded) + 100000,          # top bracket
    ]
    out = []
    for s in picks:
        if s < 0:
            s = 0
        out.append((s, "%.2f" % truth_tax(s, ded, spec["brackets"])))
    return out


def materialise_source(path: Path, spec) -> str:
    """Read variant java; for V3 inject real base64 from the ground truth."""
    text = path.read_text(encoding="utf-8")
    if "__TAX__" in text:
        brackets_json = json.dumps(spec["brackets"])
        text = text.replace("__TAX__", triple_b64(brackets_json))
        text = text.replace("__DED__", triple_b64(str(int(spec["ded"]))))
    return text


def diagnose(m, name, java_path: Path, spec):
    print("=" * 72)
    print("VARIANT", name, "  file:", java_path.name)
    ded = spec["ded"]
    brackets = spec["brackets"]
    truth = fmt([truth_tax(s, ded, brackets) for s in STD_SALARIES])
    print("  ground-truth deduction:", ded)
    print("  ground-truth 10 outputs:", truth)
    examples = worked_examples(spec)
    print("  worked-examples (salary -> tax):", examples)

    source = materialise_source(java_path, spec)

    # 1) Raw candidate extraction (what extract_parameter_candidates sees)
    cands = m.extract_parameter_candidates(source, examples)
    print("  extract_parameter_candidates -> %d candidate(s)" % len(cands))
    # how many candidates validate against the variant's worked examples?
    validating = []
    for ded_c, tbl_c in cands:
        if m._examples_match(ded_c, tbl_c, examples):
            validating.append((ded_c, tbl_c))
    print("  candidates passing the worked-examples self-check: %d" % len(validating))

    # 2) decode_parameters (the base64 fast path) standalone
    try:
        dec = m.decode_parameters(source)
        dec_ok = m._examples_match(dec[0], dec[1], examples)
        print("  decode_parameters -> deduction=%s, %d rows, validates=%s"
              % (dec[0], len(dec[1]), dec_ok))
    except Exception as exc:
        print("  decode_parameters -> raised: %s" % type(exc).__name__)

    # 3) try_python_path with config=None (exactly answer()'s no-gateway path)
    warnings = []
    outputs, best = m.try_python_path(None, source, examples, list(STD_SALARIES), 30, warnings)
    print("  try_python_path(config=None) outputs:", outputs)
    print("  warnings:", warnings)

    # 4) emulate answer()'s final assembly (no gateway -> no java path)
    if outputs is not None:
        submitted = outputs
        verdict = "VALIDATED"
    elif best is not None:
        ded_b, tbl_b = best
        submitted = fmt([m.calculate_tax(s, ded_b, tbl_b) for s in STD_SALARIES])
        verdict = "SHAPE-FALLBACK (best unvalidated params)"
    else:
        submitted = ["0.00"] * len(STD_SALARIES)
        verdict = "SHAPE-FALLBACK (all zeros)"

    answer = ",".join([m.java_version_line()] + submitted)
    seg_correct = sum(1 for a, b in zip(submitted, truth) if a == b)
    version_seg_ok = "21.0.11" in m.java_version_line()
    total_segments_correct = (1 if version_seg_ok else 0) + seg_correct
    print("  VERDICT:", verdict)
    print("  would submit answer:", answer)
    print("  segments correct vs THIS variant's truth: version=%s, taxes=%d/10 -> %d/11"
          % (version_seg_ok, seg_correct, total_segments_correct))
    print("  approx score on match2 (if this were the hidden table): %.3f/3"
          % (3.0 * total_segments_correct / 11.0))
    return dict(name=name, verdict=verdict, submitted=submitted, truth=truth,
                segs=total_segments_correct)


def main():
    m = load_skill()
    print("java_version_line() ->", m.java_version_line())
    results = []
    results.append(diagnose(m, "V1 prose-comments (public values, no base64)",
                            HERE / "V1_prose_comments.java", V1))
    results.append(diagnose(m, "V2 parallel-arrays (new values, ded=6000)",
                            HERE / "V2_parallel_arrays_changed.java", V2))
    results.append(diagnose(m, "V3 base64 same-structure (new values, ded=5500)",
                            HERE / "V3_base64_changed_values.java", V3))
    results.append(diagnose(m, "V4 2d-literal percent (new values, ded=5000)",
                            HERE / "V4_2d_literal_percent.java", V4))

    print("=" * 72)
    print("SUMMARY")
    for r in results:
        print("  %-46s %-34s segs=%d/11" % (r["name"][:46], r["verdict"][:34], r["segs"]))


if __name__ == "__main__":
    main()
