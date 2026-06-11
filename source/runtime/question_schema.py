from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def load_task_records(path: str | Path) -> list[dict[str, Any]]:
    task_path = Path(path)
    with task_path.open("r", encoding="utf-8") as handle:
        data = json.load(handle)

    if isinstance(data, list):
        records = data
    elif isinstance(data, dict):
        records = None
        for key in ("questions", "tasks", "items"):
            if key in data:
                records = data[key]
                break
    else:
        records = None

    if not isinstance(records, list):
        raise ValueError("Task file must contain a JSON list, or an object with questions/tasks/items.")

    result = []
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("Each task item must be a JSON object.")
        result.append(item)
    return result


def public_question_fields(task: dict[str, Any]) -> dict[str, Any]:
    """Return the fields visible to the contestant Agent.

    Keeps the human-useful context the platform ships with each task: ``title``
    and ``explanation`` (the latter describes the runtime variants we must
    generalize over), plus the per-question ``tools``/``skills``/``sub_agents``
    hints. Idempotent: safe to apply to an already-trimmed dict.
    """

    question = task.get("question", task.get("description"))
    if not isinstance(question, str) or not question.strip():
        raise ValueError(f"Task {task.get('id', '<unknown>')} is missing a non-empty question.")

    public: dict[str, Any] = {}
    if "id" in task:
        public["id"] = task["id"]
    public["question"] = question
    for optional_key in ("title", "explanation"):
        value = task.get(optional_key)
        if isinstance(value, str) and value.strip():
            public[optional_key] = value
    if task.get("files"):
        public["files"] = task["files"]
    for hint_key in ("tools", "skills", "sub_agents"):
        value = task.get(hint_key)
        if value:
            public[hint_key] = value
    return public
