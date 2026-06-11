"""Regression bench: score a results.json and guard the free-score floors.

Free-score anchors that must never regress:
    1_1 >= 2.0, 1_3 >= 2.0, 3_2 >= 5.0

If any anchor drops below its floor, the bench prints a FAIL line per breach and
exits non-zero. The current 2_2 earned score is always printed so improvements
there are visible.

Pure-ASCII output (Windows GBK console safe).

Usage:
    python -m source.eval.regression <results.json> <question_disc.json>
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List, Optional

from source.eval.score import _load_json, format_report, score_results


# (question id, floor) pairs that protect the calibrated free scores.
FREE_SCORE_FLOORS = (
    ("1_1", 2.0),
    ("1_3", 2.0),
    ("3_2", 5.0),
)

# Earned scores worth surfacing even though they are not guarded.
WATCH_IDS = ("2_2",)

# Floating point slack so 2.0 vs 1.9999999998 does not false-trip.
EPS = 1e-6


def check_regression(report: Dict[str, Any]) -> List[str]:
    """Return a list of FAIL message lines (empty when all floors hold)."""
    earned_by_id = {row["id"]: row["earned"] for row in report["per_question"]}
    failures: List[str] = []
    for qid, floor in FREE_SCORE_FLOORS:
        earned = earned_by_id.get(qid)
        if earned is None:
            failures.append("FAIL %s: missing from results (floor %.1f)" % (qid, floor))
        elif earned < floor - EPS:
            failures.append(
                "FAIL %s: earned %.3f < floor %.1f" % (qid, earned, floor)
            )
    return failures


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: python -m source.eval.regression <results.json> <question_disc.json>")
        return 2

    results_list = _load_json(args[0])
    disc_list = _load_json(args[1])
    if not isinstance(results_list, list) or not isinstance(disc_list, list):
        print("error: both inputs must be JSON arrays")
        return 2

    report = score_results(results_list, disc_list)
    print(format_report(report))
    print("")

    earned_by_id = {row["id"]: row["earned"] for row in report["per_question"]}
    for qid in WATCH_IDS:
        earned = earned_by_id.get(qid)
        if earned is None:
            print("WATCH %s: missing from results" % qid)
        else:
            print("WATCH %s: earned %.3f" % (qid, earned))

    print("")
    print("Free-score floors:")
    for qid, floor in FREE_SCORE_FLOORS:
        earned = earned_by_id.get(qid)
        status = "OK"
        shown = -1.0 if earned is None else earned
        if earned is None or earned < floor - EPS:
            status = "FAIL"
        print("  %-4s floor %.1f earned %.3f  [%s]" % (qid, floor, shown, status))

    failures = check_regression(report)
    if failures:
        print("")
        print("REGRESSION DETECTED:")
        for line in failures:
            print("  " + line)
        return 1

    print("")
    print("REGRESSION CHECK PASSED (all free-score floors held).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
