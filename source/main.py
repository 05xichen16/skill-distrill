from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from source.runtime.batch_runner import BatchRunner


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Skill distillation contest demo runner")
    parser.add_argument(
        "--question",
        default="source/examples/questions.json",
        help="Path to question JSON file.",
    )
    parser.add_argument(
        "--output",
        default="source/outputs/result.json",
        help="Path to output result JSON file.",
    )
    return parser.parse_args()


async def amain() -> None:
    args = parse_args()
    runner = BatchRunner()
    results = await runner.run_file(
        question_path=Path(args.question),
        output_path=Path(args.output),
    )
    print(f"done: {len(results)} answers written")
    print(f"result saved to: {Path(args.output).resolve()}")


if __name__ == "__main__":
    asyncio.run(amain())
