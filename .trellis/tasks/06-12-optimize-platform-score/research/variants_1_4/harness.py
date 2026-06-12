#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Research harness for the 1_4 interface_test skill.

Drives the REAL skill's ``answer()`` against either the unmodified public
input folder (baseline) or a variant folder, with the model seam either
disabled (pure-code ``infer_steps_from_case`` + conservative-pass) or pointed
at the live 35B gateway. Reports failing-IDs, judged/unjudged counts and the
ratio vs the canonical reference. NEVER edits the real skill source.

Usage:
    PYTHONIOENCODING=utf-8 python harness.py <doc_dir> [--model] [--reset]
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
import urllib.request

REF = ["TC009", "TC011", "TC014", "TC015", "TC016", "TC020"]

SKILL_PATH = (
    r"D:\code\python_projects\python_demo\source\solution\skills"
    r"\interface_test\scripts\run.py"
)


def load_skill():
    spec = importlib.util.spec_from_file_location("interface_skill", SKILL_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def reset_service(base_url: str) -> None:
    req = urllib.request.Request(
        base_url.rstrip("/") + "/api/debug/reset",
        data=b"",
        headers={"X-Package-Id": os.getenv("PACKAGE_ID", "")},
        method="POST",
    )
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:  # noqa: BLE001
        print("reset failed (continuing):", exc, file=sys.stderr)


def ratio_by_position(answer_ids, ref_ids):
    """Mimic a position-sensitive ratio grader: fraction of reference
    positions that match exactly, penalised by length mismatch.

    We report several views so the verdict does not hinge on one grader guess:
      - exact_match: answer == ref (ordered)
      - positional: count of i where answer[i]==ref[i], over max(len)
      - set_f1: order-free overlap (for context only)
    """
    exact = answer_ids == ref_ids
    n = max(len(answer_ids), len(ref_ids)) or 1
    pos_hits = sum(
        1 for i in range(min(len(answer_ids), len(ref_ids)))
        if answer_ids[i] == ref_ids[i]
    )
    positional = pos_hits / n
    aset, rset = set(answer_ids), set(ref_ids)
    tp = len(aset & rset)
    prec = tp / len(aset) if aset else 0.0
    rec = tp / len(rset) if rset else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return {
        "exact_match": exact,
        "positional_ratio": round(positional, 4),
        "positional_over6": round(pos_hits / len(ref_ids) * 6, 3),
        "set_f1": round(f1, 4),
        "pos_hits": pos_hits,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_dir")
    ap.add_argument("--model", action="store_true",
                    help="use the live MODEL_* gateway (else force config=None)")
    ap.add_argument("--reset", action="store_true",
                    help="POST /api/debug/reset before the run")
    args = ap.parse_args()

    skill = load_skill()

    if not args.model:
        # Force the offline/pure-code path: blank the model env so
        # _model_config() returns None inside answer().
        for k in ("MODEL_CHAT_COMPLETIONS_URL", "MODEL_BASE_URL",
                  "MODEL_API_KEY", "MODEL_NAME"):
            os.environ.pop(k, None)

    doc_dir = os.path.abspath(args.doc_dir)
    if args.reset:
        reset_service("http://127.0.0.1:18081")

    req = {
        "task_description": "verify which test cases fail by calling the service",
        "doc_dir": doc_dir,
        "_runtime": {
            "question_dir": os.path.dirname(doc_dir),
            "allowed_file_paths": [doc_dir],
            "question_id": "1_4",
        },
    }

    config_present = skill._model_config() is not None
    try:
        result = skill.answer(req)
        raised = None
    except Exception as exc:  # noqa: BLE001 - capture the degraded-raise path
        result = None
        raised = "%s: %s" % (type(exc).__name__, exc)

    print("=" * 70)
    print("doc_dir       :", doc_dir)
    print("model gateway :", "ON" if config_present else "OFF (config=None)")
    if raised:
        print("answer() RAISED:", raised)
        print("(this is the degraded-output guard at run.py ~1325)")
        return

    answer = result["answer"]
    failed = result["failed"]
    n = result["n"]
    unjudged = result.get("unjudged", 0)
    per_case = result["per_case"]

    judged_false = [c["id"] for c in per_case if not c.get("judged")]
    print("n cases       :", n)
    print("unjudged      :", unjudged, judged_false)
    print("answer        :", answer)
    print("reference     :", ",".join(REF))
    grade = ratio_by_position(failed, REF)
    for k, v in grade.items():
        print("  %-16s: %s" % (k, v))
    print("-" * 70)
    print("per_case detail (id | passed | judged | reason):")
    for c in per_case:
        print("  %-6s | pass=%-5s | judged=%-5s | %s"
              % (c["id"], c["passed"], c.get("judged"), c.get("reason", "")[:80]))


if __name__ == "__main__":
    main()
