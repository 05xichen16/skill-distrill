"""Offline tests for the prompt_learn_classify skill.

Fully offline: the model gateway is replaced by an injected fake classifier, so
nothing touches the network. Covers the behaviours the grader depends on:

- dynamic class discovery from the training labels (2-class and 4-class);
- label normalisation (exact / noisy / longest-first / case-insensitive);
- single-image failure -> fallback label with no dropped or misindexed segment;
- numeric-order assembly of ``<i><LABEL>`` even from shuffled filenames;
- self-eval accuracy when same-named ``.txt`` ground truth exists.

Standard-library unittest.
"""
from __future__ import annotations

import importlib.util
import tempfile
import unittest
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

REPO_ROOT = Path(__file__).resolve().parents[3]
SKILL_RUN = (
    REPO_ROOT
    / "source"
    / "solution"
    / "skills"
    / "prompt_learn_classify"
    / "scripts"
    / "run.py"
)

# A 1x1 JPEG so the loader's image-extension filter and byte reads work.
_TINY_JPEG = bytes(
    [
        0xFF, 0xD8, 0xFF, 0xDB, 0x00, 0x43, 0x00, 0x03, 0x02, 0x02, 0x02, 0x02,
        0x02, 0x03, 0x02, 0x02, 0x02, 0x03, 0x03, 0x03, 0x03, 0x04, 0x06, 0x04,
        0x04, 0x04, 0x04, 0x04, 0x08, 0x06, 0x06, 0x05, 0x06, 0x09, 0x08, 0x0A,
        0x0A, 0x09, 0x08, 0x09, 0x09, 0x0A, 0x0C, 0x0F, 0x0C, 0x0A, 0x0B, 0x0E,
        0x0B, 0x09, 0x09, 0x0D, 0x11, 0x0D, 0x0E, 0x0F, 0x10, 0x10, 0x11, 0x10,
        0x0A, 0x0C, 0x12, 0x13, 0x12, 0x10, 0x13, 0x0F, 0x10, 0x10, 0x10, 0xFF,
        0xC9, 0x00, 0x0B, 0x08, 0x00, 0x01, 0x00, 0x01, 0x01, 0x01, 0x11, 0x00,
        0xFF, 0xCC, 0x00, 0x06, 0x00, 0x10, 0x10, 0x05, 0xFF, 0xDA, 0x00, 0x08,
        0x01, 0x01, 0x00, 0x00, 0x3F, 0x00, 0xD2, 0xCF, 0x20, 0xFF, 0xD9,
    ]
)


def _load_module():
    spec = importlib.util.spec_from_file_location("prompt_learn_classify_run", SKILL_RUN)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MOD = _load_module()


def _write_image(directory: Path, stem: str, label: Optional[str] = None) -> None:
    (directory / ("%s.jpg" % stem)).write_bytes(_TINY_JPEG)
    if label is not None:
        # No trailing newline, matching the real training labels.
        (directory / ("%s.txt" % stem)).write_bytes(label.encode("utf-8"))


def _fake_classifier(responses_by_name: Dict[str, str], default: str = "") -> Callable[..., str]:
    """Return a classifier keyed on the image being classified (the last image).

    The skill always appends the image-to-classify as the final (name, bytes)
    entry, so we look it up by basename.
    """

    def classifier(config: Dict[str, str], prompt: str,
                   images: List[Tuple[str, bytes]], timeout: int) -> str:
        name = images[-1][0]
        if name not in responses_by_name:
            return default
        value = responses_by_name[name]
        if isinstance(value, Exception):
            raise value
        return value

    return classifier


def _runtime_args(val_dir: Path, train_dir: Path, classifier, **extra) -> Dict[str, Any]:
    args: Dict[str, Any] = {
        "task_description": "Classify each image into one of the labels.",
        "train_dir": str(train_dir),
        "val_dir": str(val_dir),
        "_runtime": {"question_dir": str(val_dir.parent), "question_id": "test"},
    }
    args.update(extra)
    return args


def _force_offline_env() -> None:
    """Ensure tests never reach a real gateway even if env is configured."""
    import os

    for key in ("MODEL_CHAT_COMPLETIONS_URL", "MODEL_BASE_URL", "MODEL_API_KEY",
                "MODEL_NAME", "PACKAGE_ID", "packageId"):
        os.environ.pop(key, None)


class ClassDiscoveryTest(unittest.TestCase):
    def setUp(self) -> None:
        _force_offline_env()

    def test_two_classes_discovered_in_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = root / "train"
            train.mkdir()
            _write_image(train, "1", "CAT")
            _write_image(train, "2", "DOG")
            _write_image(train, "3", "CAT")
            pairs, classes = MOD.load_training(str(train))
            self.assertEqual(classes, ["CAT", "DOG"])
            self.assertEqual(len(pairs), 3)

    def test_four_classes_discovered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = root / "train"
            train.mkdir()
            for stem, label in [("1", "A"), ("2", "B"), ("3", "C"), ("4", "D"), ("5", "A")]:
                _write_image(train, stem, label)
            _, classes = MOD.load_training(str(train))
            self.assertEqual(set(classes), {"A", "B", "C", "D"})
            self.assertEqual(len(classes), 4)


class LabelNormalizationTest(unittest.TestCase):
    CLASSES = ["PASS", "FAIL", "NOT_INVOLVED"]
    FALLBACK = "FAIL"

    def test_exact_match(self) -> None:
        label, matched = MOD.normalize_label("PASS", self.CLASSES, self.FALLBACK)
        self.assertEqual(label, "PASS")
        self.assertTrue(matched)

    def test_case_insensitive(self) -> None:
        label, matched = MOD.normalize_label("pass", self.CLASSES, self.FALLBACK)
        self.assertEqual(label, "PASS")
        self.assertTrue(matched)

    def test_noisy_response(self) -> None:
        label, matched = MOD.normalize_label("The answer is PASS.", self.CLASSES, self.FALLBACK)
        self.assertEqual(label, "PASS")
        self.assertTrue(matched)

    def test_not_involved_not_stolen_by_pass(self) -> None:
        # NOT_INVOLVED must win over a shorter class even though the response
        # could be argued to "contain" other tokens; longest-first wins.
        label, matched = MOD.normalize_label("NOT_INVOLVED", self.CLASSES, self.FALLBACK)
        self.assertEqual(label, "NOT_INVOLVED")
        self.assertTrue(matched)

    def test_not_involved_in_noisy_response(self) -> None:
        label, matched = MOD.normalize_label(
            "Label: NOT_INVOLVED (no hands visible)", self.CLASSES, self.FALLBACK
        )
        self.assertEqual(label, "NOT_INVOLVED")
        self.assertTrue(matched)

    def test_unparseable_falls_back(self) -> None:
        label, matched = MOD.normalize_label("???", self.CLASSES, self.FALLBACK)
        self.assertEqual(label, self.FALLBACK)
        self.assertFalse(matched)


class SingleImageFailureTest(unittest.TestCase):
    def setUp(self) -> None:
        _force_offline_env()

    def test_failed_image_gets_fallback_without_dropping_segments(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = root / "train"
            val = root / "val"
            train.mkdir()
            val.mkdir()
            # 2 classes; FAIL appears more often so it is the fallback.
            _write_image(train, "1", "FAIL")
            _write_image(train, "2", "FAIL")
            _write_image(train, "3", "PASS")
            for stem in ("1", "2", "3"):
                _write_image(val, stem)

            # Image 2 always raises -> must end up as the fallback label.
            responses = {
                "1.jpg": "PASS",
                "2.jpg": RuntimeError("gateway down"),
                "3.jpg": "PASS",
            }
            args = _runtime_args(val, train, None, few_shot_k=0)
            # Force a real config so prediction is attempted (then fails).
            import os

            os.environ["MODEL_CHAT_COMPLETIONS_URL"] = "http://example.invalid/v1/chat/completions"
            os.environ["MODEL_API_KEY"] = "sk-test"
            os.environ["MODEL_NAME"] = "test-model"
            os.environ["PROMPT_LEARN_RETRIES"] = "2"
            try:
                result = MOD.classify(args, classifier=_fake_classifier(responses))
            finally:
                _force_offline_env()
                os.environ.pop("PROMPT_LEARN_RETRIES", None)

            self.assertEqual(result["val_total"], 3)
            self.assertEqual(len(result["predictions"]), 3)
            # Indices are 1..3 contiguous, in order.
            self.assertEqual([p["idx"] for p in result["predictions"]], [1, 2, 3])
            # The failed image got the fallback (FAIL), others got PASS.
            labels = [p["label"] for p in result["predictions"]]
            self.assertEqual(labels, ["PASS", "FAIL", "PASS"])
            self.assertEqual(result["answer"], "1PASS,2FAIL,3PASS")
            self.assertGreaterEqual(result["fallback_used"], 1)
            self.assertEqual(result["failed"], 1)


class NumericOrderTest(unittest.TestCase):
    def setUp(self) -> None:
        _force_offline_env()

    def test_assembled_in_numeric_not_lexical_order(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = root / "train"
            val = root / "val"
            train.mkdir()
            val.mkdir()
            _write_image(train, "1", "PASS")
            _write_image(train, "2", "FAIL")
            # Create 1, 2, 10, 11 - lexical order would put 10/11 before 2.
            for stem in ("1", "2", "10", "11"):
                _write_image(val, stem)

            responses = {
                "1.jpg": "PASS",
                "2.jpg": "FAIL",
                "10.jpg": "PASS",
                "11.jpg": "FAIL",
            }
            args = _runtime_args(val, train, None)
            import os

            os.environ["MODEL_CHAT_COMPLETIONS_URL"] = "http://example.invalid/v1/chat/completions"
            os.environ["MODEL_API_KEY"] = "sk-test"
            os.environ["MODEL_NAME"] = "test-model"
            try:
                result = MOD.classify(args, classifier=_fake_classifier(responses))
            finally:
                _force_offline_env()

            # Segment i must carry image <i>.jpg's label, numeric order.
            self.assertEqual(result["answer"], "1PASS,2FAIL,3PASS,4FAIL")
            self.assertEqual([p["idx"] for p in result["predictions"]], [1, 2, 3, 4])


class SelfEvalTest(unittest.TestCase):
    def setUp(self) -> None:
        _force_offline_env()

    def test_accuracy_computed_when_truth_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = root / "train"
            train.mkdir()
            # Use the same labelled dir as both train and val so each val image
            # has a .txt ground truth -> accuracy is computed.
            _write_image(train, "1", "PASS")
            _write_image(train, "2", "FAIL")
            _write_image(train, "3", "PASS")
            _write_image(train, "4", "FAIL")

            # Predict 3 of 4 correctly (image 4 -> wrong).
            responses = {
                "1.jpg": "PASS",
                "2.jpg": "FAIL",
                "3.jpg": "PASS",
                "4.jpg": "PASS",  # truth is FAIL -> wrong
            }
            args = {
                "task_description": "Classify.",
                "train_dir": str(train),
                "val_dir": str(train),
                "_runtime": {"question_dir": str(root), "question_id": "test"},
            }
            import os

            os.environ["MODEL_CHAT_COMPLETIONS_URL"] = "http://example.invalid/v1/chat/completions"
            os.environ["MODEL_API_KEY"] = "sk-test"
            os.environ["MODEL_NAME"] = "test-model"
            try:
                result = MOD.classify(args, classifier=_fake_classifier(responses))
            finally:
                _force_offline_env()

            self.assertIn("accuracy", result)
            self.assertEqual(result["accuracy"]["n"], 4)
            self.assertEqual(result["accuracy"]["correct"], 3)
            self.assertAlmostEqual(result["accuracy"]["acc"], 0.75, places=4)

    def test_no_accuracy_without_truth(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = root / "train"
            val = root / "val"
            train.mkdir()
            val.mkdir()
            _write_image(train, "1", "PASS")
            _write_image(train, "2", "FAIL")
            # Validation images have NO .txt -> accuracy absent.
            _write_image(val, "1")
            _write_image(val, "2")

            responses = {"1.jpg": "PASS", "2.jpg": "FAIL"}
            args = _runtime_args(val, train, None)
            import os

            os.environ["MODEL_CHAT_COMPLETIONS_URL"] = "http://example.invalid/v1/chat/completions"
            os.environ["MODEL_API_KEY"] = "sk-test"
            os.environ["MODEL_NAME"] = "test-model"
            try:
                result = MOD.classify(args, classifier=_fake_classifier(responses))
            finally:
                _force_offline_env()

            self.assertNotIn("accuracy", result)


class FallbackChoiceTest(unittest.TestCase):
    def setUp(self) -> None:
        _force_offline_env()

    def test_fallback_is_most_frequent_training_class(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            train = root / "train"
            val = root / "val"
            train.mkdir()
            val.mkdir()
            # NOT_INVOLVED is most frequent -> it must be the fallback.
            for stem, label in [("1", "PASS"), ("2", "NOT_INVOLVED"),
                                 ("3", "NOT_INVOLVED"), ("4", "NOT_INVOLVED")]:
                _write_image(train, stem, label)
            _write_image(val, "1")

            # Model returns gibberish -> normaliser falls back.
            responses = {"1.jpg": "no idea"}
            args = _runtime_args(val, train, None)
            import os

            os.environ["MODEL_CHAT_COMPLETIONS_URL"] = "http://example.invalid/v1/chat/completions"
            os.environ["MODEL_API_KEY"] = "sk-test"
            os.environ["MODEL_NAME"] = "test-model"
            try:
                result = MOD.classify(args, classifier=_fake_classifier(responses))
            finally:
                _force_offline_env()

            self.assertEqual(result["predictions"][0]["label"], "NOT_INVOLVED")
            self.assertEqual(result["answer"], "1NOT_INVOLVED")


if __name__ == "__main__":
    unittest.main()
