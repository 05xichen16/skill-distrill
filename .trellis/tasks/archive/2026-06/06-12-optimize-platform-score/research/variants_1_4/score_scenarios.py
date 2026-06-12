#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Score every measured 1_4 answer with the REAL platform grader.

Uses source/eval/score.py:score_ratio (the calibrated platform semantics) and
the verbatim reference from question_disc.json (score weight = 2.0).
"""
from __future__ import annotations

import importlib.util
import os

SCORE_PATH = r"D:\code\python_projects\python_demo\source\eval\score.py"
REF = "TC009,TC011,TC014,TC015,TC016,TC020"
WEIGHT = 2.0


def load_scorer():
    spec = importlib.util.spec_from_file_location("eval_score", SCORE_PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# Every measured answer string from the experiments.
SCENARIOS = [
    ("BASELINE public, pure-code (no model)", "TC009,TC011,TC014,TC015,TC016,TC020"),
    ("BASELINE public, with model", "TC009,TC011,TC014,TC015,TC016,TC020"),
    ("VARIANT reworded, pure-code (real skill)", "TC006,TC007,TC008,TC009,TC011,TC014,TC015,TC016,TC020"),
    ("VARIANT aggressive, pure-code (real skill)", "TC006,TC007,TC008,TC009,TC011,TC014,TC015,TC016,TC020"),
    ("VARIANT reworded, with model (real skill)", "TC006,TC007,TC008,TC009,TC011,TC014,TC015,TC016,TC020"),
    ("VARIANT reworded, PROTO-FIX, no model (abstain->conservative)", "TC009,TC011,TC014,TC020"),
    ("VARIANT reworded, PROTO-FIX, with model", "TC006,TC009,TC011,TC014,TC015,TC016,TC020"),
    # hypotheticals for context:
    ("HYPOTHETICAL empty answer (all-pass)", ""),
    ("HYPOTHETICAL perfect", "TC009,TC011,TC014,TC015,TC016,TC020"),
]


def main():
    s = load_scorer()
    print("reference:", REF, " weight:", WEIGHT)
    print("=" * 92)
    print("%-58s | %-7s | %s" % ("scenario", "points", "detail"))
    print("-" * 92)
    for label, ans in SCENARIOS:
        earned, detail = s.score_ratio(REF, ans, WEIGHT)
        print("%-58s | %6.3f  | %s" % (label, earned, detail))


if __name__ == "__main__":
    main()
