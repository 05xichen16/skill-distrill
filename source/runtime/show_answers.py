from __future__ import annotations

import argparse
import json
import textwrap
from pathlib import Path
from typing import Any


def _load_results(path: Path) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)
    if not isinstance(data, list):
        raise ValueError("Result file must contain a JSON list.")
    return [item for item in data if isinstance(item, dict)]


def _indent(text: str, *, width: int = 100) -> str:
    wrapped_lines = []
    for line in str(text or "").splitlines() or [""]:
        wrapped = textwrap.wrap(line, width=width) or [""]
        wrapped_lines.extend(f"  {part}" for part in wrapped)
    return "\n".join(wrapped_lines)


def print_answers(results: list[dict[str, Any]], *, result_path: Path) -> None:
    print(f"result: {result_path.resolve()}")
    print(f"items: {len(results)}")
    print("")

    for index, item in enumerate(results, start=1):
        qid = item.get("id", index)
        print(f"[{index}] id: {qid}")
        print("answer:")
        print(_indent(str(item.get("answer", ""))))
        print("-" * 80)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Print readable answers from a contest result JSON file.")
    parser.add_argument(
        "result",
        nargs="?",
        default="source/outputs/result.json",
        help="Path to result JSON file.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    result_path = Path(args.result)
    results = _load_results(result_path)
    print_answers(results, result_path=result_path)


if __name__ == "__main__":
    main()
