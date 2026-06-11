"""Tests for the AGENT_DEMO_ONLY_QUESTION_IDS single-question probe switch.

The platform keeps the LATEST submission's score (submission count is only the
third tiebreaker), so a probe submission may answer just the whitelisted
question(s) to isolate variant behaviour while every other question instantly
returns an empty answer — no context build, no model call, no skill
subprocess. Two foot-guns are guarded:

* a prominent banner whenever the probe whitelist is active, so a forgotten
  switch cannot silently gut the closing full submission, and
* a whitelist matching no real question id is ignored with a loud warning and
  the run stays FULL — a typo must never produce an all-empty submission.

Offline, standard-library unittest: ContestantAgent is replaced by a recording
stub and batch_runner's load_dotenv is no-op'd, so no model endpoint is
touched and repo .env contents cannot leak into the assertions.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from contextlib import ExitStack, redirect_stderr, redirect_stdout
from io import StringIO
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import source.runtime.batch_runner as batch_runner_module
from source.runtime.batch_runner import BatchRunner

QUESTION_IDS = ["1_1", "1_2", "1_3", "1_4", "2_1", "2_2", "2_3", "3_1", "3_2", "3_3"]
BANNER = "[probe] AGENT_DEMO_ONLY_QUESTION_IDS active"


class BatchRunnerProbeTest(unittest.IsolatedAsyncioTestCase):
    async def _run_batch(self, *, only: str | None, concurrency: str = "1") -> SimpleNamespace:
        """Run a 10-question batch with ContestantAgent stubbed to a recorder.

        ``only=None`` removes AGENT_DEMO_ONLY_QUESTION_IDS from the env
        entirely; any string (including "") is set verbatim.
        """

        solved: list[str] = []
        built: list[str] = []

        class RecordingAgent:
            async def solve(self, *, question, context):
                solved.append(str(question.get("id")))
                return f"answer-{question.get('id')}"

        original_build = BatchRunner._build_context

        def counting_build(runner, *, question, question_dir):
            built.append(str(question.get("id")))
            return original_build(runner, question=question, question_dir=question_dir)

        stdout, stderr = StringIO(), StringIO()
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            question_path = tmp_path / "questions.json"
            question_path.write_text(
                json.dumps([{"id": qid, "question": f"question {qid}"} for qid in QUESTION_IDS]),
                encoding="utf-8",
            )
            output_path = tmp_path / "results.json"
            with ExitStack() as stack:
                stack.enter_context(mock.patch.dict(os.environ))
                os.environ.pop("AGENT_DEMO_ONLY_QUESTION_IDS", None)
                if only is not None:
                    os.environ["AGENT_DEMO_ONLY_QUESTION_IDS"] = only
                os.environ["AGENT_DEMO_CONCURRENCY"] = concurrency
                stack.enter_context(
                    mock.patch.object(batch_runner_module, "ContestantAgent", RecordingAgent)
                )
                stack.enter_context(
                    mock.patch.object(batch_runner_module, "load_dotenv", lambda: None)
                )
                stack.enter_context(mock.patch.object(BatchRunner, "_build_context", counting_build))
                stack.enter_context(redirect_stdout(stdout))
                stack.enter_context(redirect_stderr(stderr))
                results = await BatchRunner().run_file(
                    question_path=question_path, output_path=output_path
                )
            on_disk = json.loads(output_path.read_text(encoding="utf-8"))
        return SimpleNamespace(
            results=results,
            on_disk=on_disk,
            solved=solved,
            built=built,
            stdout=stdout.getvalue(),
            stderr=stderr.getvalue(),
        )

    def _answers(self, results: list[dict[str, str]]) -> dict[str, str]:
        return {item["id"]: item["answer"] for item in results}

    # --- probe active ------------------------------------------------------
    async def test_probe_whitelist_answers_only_listed_question(self) -> None:
        run = await self._run_batch(only="3_2")
        # Only the whitelisted question reaches the solve flow or builds a context.
        self.assertEqual(run.solved, ["3_2"])
        self.assertEqual(run.built, ["3_2"])
        # results keep ALL ids in input order; skipped answers are empty strings.
        self.assertEqual([item["id"] for item in run.results], QUESTION_IDS)
        answers = self._answers(run.results)
        self.assertEqual(answers["3_2"], "answer-3_2")
        for qid in QUESTION_IDS:
            if qid != "3_2":
                self.assertEqual(answers[qid], "")
        # results.json on disk mirrors the full id set.
        self.assertEqual([item["id"] for item in run.on_disk], QUESTION_IDS)
        self.assertEqual(self._answers(run.on_disk), answers)
        # Banner names the effective ids and the skip count.
        self.assertIn(BANNER, run.stdout)
        self.assertIn("[3_2]", run.stdout)
        self.assertIn("skipping 9 question(s)", run.stdout)

    async def test_probe_concurrent_path_and_multi_id_parsing(self) -> None:
        # Spaces around ids are stripped; the concurrent worker path goes
        # through the same _run_one choke point.
        run = await self._run_batch(only=" 3_2 , 1_4 ", concurrency="3")
        self.assertEqual(sorted(run.solved), ["1_4", "3_2"])
        self.assertEqual(sorted(run.built), ["1_4", "3_2"])
        self.assertEqual([item["id"] for item in run.results], QUESTION_IDS)
        answers = self._answers(run.results)
        self.assertEqual(answers["3_2"], "answer-3_2")
        self.assertEqual(answers["1_4"], "answer-1_4")
        for qid in QUESTION_IDS:
            if qid not in {"3_2", "1_4"}:
                self.assertEqual(answers[qid], "")
        self.assertIn(BANNER, run.stdout)
        self.assertIn("[1_4, 3_2]", run.stdout)
        self.assertIn("skipping 8 question(s)", run.stdout)

    # --- probe inactive (full run) ------------------------------------------
    async def test_env_unset_runs_every_question(self) -> None:
        run = await self._run_batch(only=None)
        self.assertEqual(run.solved, QUESTION_IDS)
        self.assertEqual(run.built, QUESTION_IDS)
        answers = self._answers(run.results)
        for qid in QUESTION_IDS:
            self.assertEqual(answers[qid], f"answer-{qid}")
        self.assertNotIn("[probe]", run.stdout)
        self.assertNotIn("[probe]", run.stderr)

    async def test_env_blank_or_separators_only_runs_every_question(self) -> None:
        for value in ("", "   ", " , ,"):
            with self.subTest(value=value):
                run = await self._run_batch(only=value)
                self.assertEqual(run.solved, QUESTION_IDS)
                self.assertNotIn("[probe]", run.stdout)
                self.assertNotIn("[probe]", run.stderr)

    async def test_partial_match_probes_valid_id_without_fallback(self) -> None:
        # One valid + one unknown id: the valid id is probed normally; the
        # typo fallback is reserved for an EMPTY intersection only.
        run = await self._run_batch(only="3_2,9_9")
        self.assertEqual(run.solved, ["3_2"])
        self.assertEqual(run.built, ["3_2"])
        self.assertNotIn("running ALL questions", run.stderr)
        self.assertIn(BANNER, run.stdout)
        self.assertIn("[3_2]", run.stdout)
        self.assertIn("skipping 9 question(s)", run.stdout)
        answers = self._answers(run.results)
        self.assertEqual(answers["3_2"], "answer-3_2")
        for qid in QUESTION_IDS:
            if qid != "3_2":
                self.assertEqual(answers[qid], "")

    # --- typo guard ----------------------------------------------------------
    async def test_typo_whitelist_warns_and_falls_back_to_full_run(self) -> None:
        run = await self._run_batch(only="2-3, 9_9")
        # Loud warning, then full run: every question is solved for real.
        self.assertIn("WARNING", run.stderr)
        self.assertIn("running ALL questions", run.stderr)
        self.assertNotIn(BANNER, run.stdout)
        self.assertEqual(run.solved, QUESTION_IDS)
        answers = self._answers(run.results)
        for qid in QUESTION_IDS:
            self.assertEqual(answers[qid], f"answer-{qid}")


if __name__ == "__main__":
    unittest.main()
