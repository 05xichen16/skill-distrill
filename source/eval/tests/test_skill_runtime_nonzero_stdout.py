"""Focused tests for SkillRuntime.run_skill's non-zero-exit handling.

A skill subprocess may deliberately emit a well-formed answer right before
dying (e.g. java_tax_calculator's emergency/deadline shape fallback). The
runtime must keep that stdout rather than dropping it and crashing the router
into the version-less model loop, which scores an exact zero on the contest's
position-sensitive graders. But genuine crash noise on stdout must still raise.

Everything is offline: each test materialises a throwaway skill package whose
entrypoint chooses its own exit code / stdout. Standard-library unittest.
"""
from __future__ import annotations

import json
import tempfile
import textwrap
import unittest
from pathlib import Path

from source.runtime.skill_runtime import SkillRuntime, _has_usable_answer


def _write_skill(skills_dir: Path, name: str, body: str) -> None:
    skill_dir = skills_dir / name
    (skill_dir / "scripts").mkdir(parents=True)
    (skill_dir / "SKILL.md").write_text(
        "---\nname: %s\ndescription: test skill\n---\n\n# %s\n" % (name, name),
        encoding="utf-8",
    )
    (skill_dir / "skill.json").write_text(
        json.dumps(
            {
                "name": name,
                "description": "test skill",
                "entrypoint": "scripts/run.py",
                "timeout_seconds": 30,
            }
        ),
        encoding="utf-8",
    )
    (skill_dir / "scripts" / "run.py").write_text(textwrap.dedent(body), encoding="utf-8")


class HasUsableAnswerTest(unittest.TestCase):
    def test_accepts_object_with_nonempty_answer(self) -> None:
        self.assertTrue(_has_usable_answer('{"answer": "openjdk version \\"21.0.11\\",0.00"}'))

    def test_rejects_empty_and_noise(self) -> None:
        for stdout in ("", "   ", "Traceback (most recent call last): boom", "[1, 2, 3]"):
            self.assertFalse(_has_usable_answer(stdout))

    def test_rejects_error_only_and_blank_answer(self) -> None:
        self.assertFalse(_has_usable_answer('{"error": "boom"}'))
        self.assertFalse(_has_usable_answer('{"answer": ""}'))
        self.assertFalse(_has_usable_answer('{"answer": "   "}'))
        self.assertFalse(_has_usable_answer('{"answer": null}'))


class RunSkillNonZeroStdoutTest(unittest.TestCase):
    def test_nonzero_exit_with_answer_is_returned(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            _write_skill(
                skills_dir,
                "emits_then_dies",
                """
                import sys
                sys.stdout.write('{"answer": "shaped,0.00"}\\n')
                sys.stdout.flush()
                raise SystemExit(1)
                """,
            )
            runtime = SkillRuntime(skills_dir=skills_dir)
            result = runtime.run_skill("emits_then_dies", {})
            self.assertEqual(json.loads(result)["answer"], "shaped,0.00")

    def test_nonzero_exit_without_answer_still_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            _write_skill(
                skills_dir,
                "dies_with_noise",
                """
                import sys
                sys.stdout.write("partial garbage, not json\\n")
                sys.stderr.write("boom\\n")
                raise SystemExit(1)
                """,
            )
            runtime = SkillRuntime(skills_dir=skills_dir)
            with self.assertRaises(RuntimeError):
                runtime.run_skill("dies_with_noise", {})

    def test_nonzero_exit_with_error_only_object_still_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            _write_skill(
                skills_dir,
                "dies_error_only",
                """
                import sys
                sys.stdout.write('{"error": "boom"}\\n')
                raise SystemExit(1)
                """,
            )
            runtime = SkillRuntime(skills_dir=skills_dir)
            with self.assertRaises(RuntimeError):
                runtime.run_skill("dies_error_only", {})

    def test_zero_exit_returns_stdout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            skills_dir = Path(tmp)
            _write_skill(
                skills_dir,
                "happy",
                """
                import sys
                sys.stdout.write('{"answer": "ok"}\\n')
                """,
            )
            runtime = SkillRuntime(skills_dir=skills_dir)
            self.assertEqual(json.loads(runtime.run_skill("happy", {}))["answer"], "ok")


if __name__ == "__main__":
    unittest.main()
