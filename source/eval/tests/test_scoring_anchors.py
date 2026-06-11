"""Anchor tests for the offline scorer.

Scoring the committed baseline against the public answer key must reproduce the
calibrated total (12.386/32) and the three free-score anchors exactly:
    1_1 = 2.0, 1_3 = 2.0, 3_2 = 5.0

Pure offline, standard-library unittest.
"""
from __future__ import annotations

import json
import unittest
from pathlib import Path

from source.eval.score import score_results

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE = REPO_ROOT / "source" / "outputs" / "baseline.json"
DISC = REPO_ROOT / "publish" / "publish_V1" / "question_disc.json"


def _load(path: Path):
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class ScoringAnchorsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.report = score_results(_load(BASELINE), _load(DISC))
        cls.earned = {row["id"]: row["earned"] for row in cls.report["per_question"]}

    def test_total_reproduces_baseline(self) -> None:
        self.assertAlmostEqual(self.report["total"], 12.386, delta=0.02)

    def test_max_is_32(self) -> None:
        self.assertAlmostEqual(self.report["max"], 32.0, delta=1e-6)

    def test_anchor_1_1(self) -> None:
        self.assertAlmostEqual(self.earned["1_1"], 2.0, delta=1e-6)

    def test_anchor_1_3(self) -> None:
        self.assertAlmostEqual(self.earned["1_3"], 2.0, delta=1e-6)

    def test_anchor_3_2(self) -> None:
        self.assertAlmostEqual(self.earned["3_2"], 5.0, delta=1e-6)

    def test_list_equal_self_match_full_score(self) -> None:
        # Feeding the reference back as the answer must yield full score for 3_3.
        disc = _load(DISC)
        q33 = next(q for q in disc if q["id"] == "3_3")
        results = [{"id": "3_3", "answer": q33["reference_answer"]}]
        report = score_results(results, [q33])
        self.assertAlmostEqual(report["total"], float(q33["score"]), delta=1e-6)


if __name__ == "__main__":
    unittest.main()
