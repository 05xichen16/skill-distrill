from __future__ import annotations

from pathlib import Path
from typing import Any

from source.runtime.question_schema import load_task_records, public_question_fields


def load_questions(path: str | Path) -> list[dict[str, Any]]:
    return [public_question_fields(item) for item in load_task_records(path)]
