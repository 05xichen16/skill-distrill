#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Same as harness.py but loads the RESEARCH prototype run_proto.py.

Usage: PYTHONIOENCODING=utf-8 python harness_proto.py <doc_dir> [--model] [--reset]
"""
from __future__ import annotations

import argparse
import importlib.util
import os
import sys
import urllib.request

REF = ["TC009", "TC011", "TC014", "TC015", "TC016", "TC020"]
PROTO = os.path.join(os.path.dirname(os.path.abspath(__file__)), "run_proto.py")


def load(path):
    spec = importlib.util.spec_from_file_location("interface_proto", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def reset_service(base_url):
    req = urllib.request.Request(base_url.rstrip("/") + "/api/debug/reset", data=b"",
                                 headers={"X-Package-Id": os.getenv("PACKAGE_ID", "")}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=5).read()
    except Exception as exc:  # noqa: BLE001
        print("reset failed:", exc, file=sys.stderr)


def grade(answer_ids, ref_ids):
    n = max(len(answer_ids), len(ref_ids)) or 1
    hits = sum(1 for i in range(min(len(answer_ids), len(ref_ids))) if answer_ids[i] == ref_ids[i])
    aset, rset = set(answer_ids), set(ref_ids)
    tp = len(aset & rset)
    prec = tp / len(aset) if aset else 0.0
    rec = tp / len(rset) if rset else 0.0
    f1 = (2 * prec * rec / (prec + rec)) if (prec + rec) else 0.0
    return {"exact": answer_ids == ref_ids, "positional_ratio": round(hits / n, 4),
            "positional_over6": round(hits / len(ref_ids) * 6, 3), "set_f1": round(f1, 4)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("doc_dir")
    ap.add_argument("--model", action="store_true")
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    skill = load(PROTO)
    if not args.model:
        for k in ("MODEL_CHAT_COMPLETIONS_URL", "MODEL_BASE_URL", "MODEL_API_KEY", "MODEL_NAME"):
            os.environ.pop(k, None)

    doc_dir = os.path.abspath(args.doc_dir)
    if args.reset:
        reset_service("http://127.0.0.1:18081")
    req = {"task_description": "verify failing cases", "doc_dir": doc_dir,
           "_runtime": {"question_dir": os.path.dirname(doc_dir), "allowed_file_paths": [doc_dir], "question_id": "1_4"}}
    cfg_on = skill._model_config() is not None
    try:
        result = skill.answer(req)
        raised = None
    except Exception as exc:  # noqa: BLE001
        result, raised = None, "%s: %s" % (type(exc).__name__, exc)

    print("=" * 70)
    print("PROTO doc_dir:", doc_dir, "| model:", "ON" if cfg_on else "OFF")
    if raised:
        print("answer() RAISED:", raised)
        return
    failed = result["failed"]
    unjudged = [c["id"] for c in result["per_case"] if not c.get("judged")]
    print("answer   :", result["answer"])
    print("reference:", ",".join(REF))
    print("unjudged :", result.get("unjudged", 0), unjudged)
    for k, v in grade(failed, REF).items():
        print("  %-16s: %s" % (k, v))
    print("-" * 70)
    for c in result["per_case"]:
        if not c["passed"] or not c.get("judged"):
            print("  %-6s pass=%-5s judged=%-5s %s" % (c["id"], c["passed"], c.get("judged"), c.get("reason", "")[:70]))


if __name__ == "__main__":
    main()
