from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from source.runtime.agent_context import AgentContext
from source.runtime.agent_registry import AgentRegistry
from source.runtime.mcp_client import LocalMCPClient
from source.runtime.question_loader import load_questions
from source.runtime.question_schema import public_question_fields
from source.runtime.result_writer import write_results
from source.solution.contestant_agent import ContestantAgent


class BatchRunner:
    def __init__(self) -> None:
        self.mcp = LocalMCPClient(agent_registry=AgentRegistry())

    async def run_file(self, *, question_path: str | Path, output_path: str | Path) -> list[dict[str, Any]]:
        question_path = Path(question_path).resolve()
        output_path = Path(output_path).resolve()
        questions = load_questions(question_path)
        question_dir = question_path.parent
        results: list[dict[str, Any]] = []

        for index, question in enumerate(questions, start=1):
            qid = str(question.get("id", index))
            print(f"[{index}/{len(questions)}] running question {qid}")
            result = await self._run_one(question=public_question(question), question_dir=question_dir)
            results.append(result)
            write_results(output_path, results)

        return results

    async def _run_one(self, *, question: dict[str, Any], question_dir: Path) -> dict[str, Any]:
        qid = str(question.get("id", "unknown"))
        try:
            context = self._build_context(question=question, question_dir=question_dir)
            answer = await ContestantAgent().solve(question=question, context=context)
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
