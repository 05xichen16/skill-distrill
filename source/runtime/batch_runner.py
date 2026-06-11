from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
import sys
from typing import Any

from source.runtime.agent_context import AgentContext
from source.runtime.agent_registry import AgentRegistry
from source.runtime.env_config import env_int, load_dotenv
from source.runtime.mcp_client import LocalMCPClient
from source.runtime.question_loader import load_questions
from source.runtime.question_schema import public_question_fields
from source.runtime.result_writer import write_results
from source.solution.contestant_agent import ContestantAgent


class BatchRunner:
    def __init__(self) -> None:
        self.mcp = LocalMCPClient(agent_registry=AgentRegistry())
        # Effective AGENT_DEMO_ONLY_QUESTION_IDS probe whitelist; None = full run.
        self._probe_question_ids: set[str] | None = None

    async def run_file(self, *, question_path: str | Path, output_path: str | Path) -> list[dict[str, Any]]:
        question_path = Path(question_path).resolve()
        output_path = Path(output_path).resolve()
        questions = load_questions(question_path)
        question_dir = question_path.parent

        load_dotenv()
        self._probe_question_ids = _resolve_probe_question_ids(questions)
        concurrency = max(1, env_int("AGENT_DEMO_CONCURRENCY", 1))
        if concurrency == 1 or len(questions) <= 1:
            return await self._run_serial(questions, question_dir=question_dir, output_path=output_path)
        return await self._run_concurrent(
            questions, question_dir=question_dir, output_path=output_path, concurrency=concurrency
        )

    async def _run_serial(
        self, questions: list[dict[str, Any]], *, question_dir: Path, output_path: Path
    ) -> list[dict[str, Any]]:
        results: list[dict[str, Any]] = []
        for index, question in enumerate(questions, start=1):
            qid = str(question.get("id", index))
            print(f"[{index}/{len(questions)}] running question {qid}")
            result = await self._run_one(question=public_question(question), question_dir=question_dir)
            results.append(result)
            write_results(output_path, results)
        return results

    async def _run_concurrent(
        self,
        questions: list[dict[str, Any]],
        *,
        question_dir: Path,
        output_path: Path,
        concurrency: int,
    ) -> list[dict[str, Any]]:
        total = len(questions)
        slots: list[dict[str, Any] | None] = [None] * total
        semaphore = asyncio.Semaphore(concurrency)
        write_lock = asyncio.Lock()

        async def worker(index: int, question: dict[str, Any]) -> None:
            qid = str(question.get("id", index + 1))
            async with semaphore:
                print(f"[{index + 1}/{total}] running question {qid}")
                result = await self._run_one(question=public_question(question), question_dir=question_dir)
            slots[index] = result
            # Flush after each completion so a 1-hour cutoff keeps finished answers.
            async with write_lock:
                write_results(output_path, [item for item in slots if item is not None])

        await asyncio.gather(*(worker(index, question) for index, question in enumerate(questions)))
        results = [item for item in slots if item is not None]
        write_results(output_path, results)
        return results

    async def _run_one(self, *, question: dict[str, Any], question_dir: Path) -> dict[str, Any]:
        qid = str(question.get("id", "unknown"))
        if self._probe_question_ids is not None and qid not in self._probe_question_ids:
            # Probe mode: out-of-whitelist questions return an empty answer
            # immediately — no context build, no model call, no skill subprocess.
            print(f"question {qid} skipped (probe whitelist)")
            return {"id": qid, "answer": ""}
        try:
            context = self._build_context(question=question, question_dir=question_dir)
            started = time.monotonic()
            answer = await ContestantAgent().solve(question=question, context=context)
            print(f"question {qid} done in {time.monotonic() - started:.1f}s")
            return {
                "id": qid,
                "answer": str(answer),
            }
        except Exception as exc:
            print(f"question {qid} failed: {exc}", file=sys.stderr)
            return {
                "id": qid,
                "answer": "",
            }

    def _build_context(
        self,
        *,
        question: dict[str, Any],
        question_dir: Path,
    ) -> AgentContext:
        files = question.get("files") or []
        allowed_file_paths = [(question_dir / path).resolve() for path in files]
        return AgentContext(
            question=question,
            question_dir=question_dir,
            allowed_file_paths=allowed_file_paths,
            allowed_tools=self.mcp.tool_names(),
            allowed_agents=self.mcp.agent_names(),
            mcp=self.mcp,
        )


def public_question(question: dict[str, Any]) -> dict[str, Any]:
    """Return the question object visible to the contestant Agent."""

    return public_question_fields(question)


def _resolve_probe_question_ids(questions: list[dict[str, Any]]) -> set[str] | None:
    """Parse AGENT_DEMO_ONLY_QUESTION_IDS into the effective probe whitelist.

    The platform keeps the LATEST submission's score, so a probe submission can
    answer only the whitelisted question(s) to isolate their variant behaviour
    while every other question instantly returns an empty answer. Returns
    ``None`` (= full run) when the env is unset/blank, or when the whitelist
    matches no actual question id — a typo must never turn a submission into
    all-empty answers.
    """

    raw = os.getenv("AGENT_DEMO_ONLY_QUESTION_IDS", "")
    requested = {part.strip() for part in raw.split(",") if part.strip()}
    if not requested:
        return None
    actual_ids = [str(question.get("id", "unknown")) for question in questions]
    effective = requested.intersection(actual_ids)
    if not effective:
        print(
            f"[probe] WARNING: AGENT_DEMO_ONLY_QUESTION_IDS={raw.strip()!r} matches no "
            f"question id (available: {', '.join(actual_ids)}); ignoring the whitelist "
            "and running ALL questions.",
            file=sys.stderr,
        )
        return None
    skipped = sum(1 for qid in actual_ids if qid not in effective)
    print(
        "[probe] AGENT_DEMO_ONLY_QUESTION_IDS active: answering only "
        f"[{', '.join(sorted(effective))}], skipping {skipped} question(s)"
    )
    return effective
