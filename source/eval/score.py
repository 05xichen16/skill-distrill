"""Offline scorer for contest ``results.json`` files.

Reimplements the platform grading semantics, calibrated against the public
answer key in ``publish/publish_V1/question_disc.json``. The baseline anchors
(1_1=2.0, 1_3=2.0, 3_2=5.0) and the total (12.386/32) are reproduced exactly.

Type semantics (rebuilt + calibrated):

- ``equal``       strip both sides, full score iff exactly equal, else 0.
- ``list_equal``  parse ref/ans as JSON arrays (fall back to comma split);
                  per-element strip compare; score = score * hits / len(ref).
- ``ratio``       split on ``,``; positional compare; score * hits / len(ref).
- ``matchN``      split on a separator (match1 uses ``;``, others ``,``); each
                  segment judged by its operator; score * hits / len(ref).
                  Segment operators:
                    or[a,b,...]      segment contains ANY of a/b/... (substring)
                    and[a,b,...]     segment contains ALL of them
                    contain[x]       segment contains x
                    is[x]            segment strip-equals x
                    <literal>        segment strip-equals the literal
- ``match5``      special case (1_3): split on ``,`` into 3 fields; first two
                  are literal-equal; the third field is split on the Chinese
                  enumeration comma and compared as an unordered set.

Pure standard library, Python 3.9 compatible.
"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, List, Optional, Tuple


# match5 splits the root-cause field on the Chinese enumeration comma (U+3001).
# Built from its codepoint so this module stays pure-ASCII on disk.
ENUM_SEP = chr(0x3001)


def _parse_list_like(text: str) -> List[str]:
    """Parse a value as a JSON array; fall back to a comma split."""
    stripped = text.strip()
    try:
        value = json.loads(stripped)
        if isinstance(value, list):
            return [str(item) for item in value]
    except (ValueError, TypeError):
        pass
    return stripped.split(",")


def score_equal(reference: str, answer: str, score: float) -> Tuple[float, str]:
    ok = answer.strip() == reference.strip()
    return (score if ok else 0.0), ("exact match" if ok else "not equal")


def score_list_equal(reference: str, answer: str, score: float) -> Tuple[float, str]:
    ref_list = [item.strip() for item in _parse_list_like(reference)]
    ans_list = [item.strip() for item in _parse_list_like(answer)]
    if not ref_list:
        return 0.0, "empty reference"

    used = [False] * len(ans_list)
    hits = 0
    for ref_item in ref_list:
        for index, ans_item in enumerate(ans_list):
            if not used[index] and ans_item == ref_item:
                used[index] = True
                hits += 1
                break
    earned = score * hits / len(ref_list)
    return earned, "%d/%d elements" % (hits, len(ref_list))


def score_ratio(reference: str, answer: str, score: float) -> Tuple[float, str]:
    ref_list = [item.strip() for item in reference.split(",")]
    ans_list = [item.strip() for item in answer.split(",")]
    if not ref_list:
        return 0.0, "empty reference"

    hits = 0
    for index, ref_item in enumerate(ref_list):
        if index < len(ans_list) and ans_list[index] == ref_item:
            hits += 1
    earned = score * hits / len(ref_list)
    return earned, "%d/%d positions" % (hits, len(ref_list))


def _segment_matches(segment: str, operator: str) -> bool:
    seg_stripped = segment.strip()
    if operator.startswith("or[") and operator.endswith("]"):
        items = operator[3:-1].split(",")
        return any(item in segment for item in items)
    if operator.startswith("and[") and operator.endswith("]"):
        items = operator[4:-1].split(",")
        return all(item in segment for item in items)
    if operator.startswith("contain[") and operator.endswith("]"):
        return operator[len("contain["):-1] in segment
    if operator.startswith("is[") and operator.endswith("]"):
        return seg_stripped == operator[3:-1].strip()
    return seg_stripped == operator.strip()


def score_match(reference: str, answer: str, score: float, sep: str) -> Tuple[float, str]:
    operators = reference.split(sep)
    segments = answer.split(sep)
    if not operators:
        return 0.0, "empty reference"

    hits = 0
    for index, operator in enumerate(operators):
        if index < len(segments) and _segment_matches(segments[index], operator):
            hits += 1
    earned = score * hits / len(operators)
    return earned, "%d/%d segments" % (hits, len(operators))


def score_match5(reference: str, answer: str, score: float) -> Tuple[float, str]:
    ref_parts = reference.split(",")
    ans_parts = answer.split(",")
    total_fields = 3
    hits = 0

    for index in range(total_fields):
        if index >= len(ref_parts) or index >= len(ans_parts):
            break
        if index < 2:
            if ans_parts[index].strip() == ref_parts[index].strip():
                hits += 1
        else:
            ref_set = {p.strip() for p in ref_parts[index].split(ENUM_SEP) if p.strip()}
            # The third field may itself contain commas, so re-join the tail.
            ans_third = ",".join(ans_parts[index:])
            ans_set = {p.strip() for p in ans_third.split(ENUM_SEP) if p.strip()}
            if ref_set == ans_set:
                hits += 1
            break
    earned = score * hits / float(total_fields)
    return earned, "%d/%d fields" % (hits, total_fields)


def score_one(qtype: str, reference: str, answer: str, score: float) -> Tuple[float, str]:
    """Score a single answer. Unknown types score 0 with a note."""
    if qtype == "equal":
        return score_equal(reference, answer, score)
    if qtype == "list_equal":
        return score_list_equal(reference, answer, score)
    if qtype == "ratio":
        return score_ratio(reference, answer, score)
    if qtype == "match5":
        return score_match5(reference, answer, score)
    if qtype.startswith("match"):
        sep = ";" if qtype == "match1" else ","
        return score_match(reference, answer, score, sep)
    return 0.0, "unknown type: %s" % qtype


def score_results(
    results_list: List[Dict[str, Any]],
    disc_list: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Score a list of answers against the discrimination/answer key.

    Returns ``{per_question: [...], total, max}``. Each per-question entry has
    ``id, type, score, earned, detail``.
    """
    answer_by_id: Dict[str, str] = {}
    for item in results_list:
        qid = str(item.get("id", ""))
        answer_by_id[qid] = str(item.get("answer", ""))

    per_question: List[Dict[str, Any]] = []
    total = 0.0
    max_score = 0.0
    for question in disc_list:
        qid = str(question.get("id", ""))
        qtype = str(question.get("type", ""))
        score = float(question.get("score", 0) or 0)
        reference = str(question.get("reference_answer", ""))
        answer = answer_by_id.get(qid, "")

        earned, detail = score_one(qtype, reference, answer, score)
        total += earned
        max_score += score
        per_question.append(
            {
                "id": qid,
                "type": qtype,
                "score": score,
                "earned": earned,
                "detail": detail,
            }
        )

    return {"per_question": per_question, "total": total, "max": max_score}


def _load_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def format_report(report: Dict[str, Any]) -> str:
    """Render a pure-ASCII score report (Windows GBK console safe)."""
    lines: List[str] = []
    lines.append("%-6s %-12s %8s %8s  %s" % ("id", "type", "score", "earned", "detail"))
    lines.append("-" * 60)
    for row in report["per_question"]:
        lines.append(
            "%-6s %-12s %8.2f %8.3f  %s"
            % (row["id"], row["type"], row["score"], row["earned"], row["detail"])
        )
    lines.append("-" * 60)
    lines.append(
        "TOTAL  %25.3f / %.1f" % (report["total"], report["max"])
    )
    return "\n".join(lines)


def main(argv: Optional[List[str]] = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) < 2:
        print("usage: python -m source.eval.score <results.json> <question_disc.json>")
        return 2

    results_path, disc_path = args[0], args[1]
    results_list = _load_json(results_path)
    disc_list = _load_json(disc_path)
    if not isinstance(results_list, list) or not isinstance(disc_list, list):
        print("error: both inputs must be JSON arrays")
        return 2

    report = score_results(results_list, disc_list)
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
