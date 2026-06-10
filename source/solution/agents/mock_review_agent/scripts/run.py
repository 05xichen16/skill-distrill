from __future__ import annotations

import json
import sys


def main() -> None:
    raw = sys.stdin.read().strip() or "{}"
    payload = json.loads(raw)
    print(
        json.dumps(
            {
                "mock_result": "mock-review-agent-ok",
                "source": "mock_sub_agent",
                "agent_name": payload.get("agent_name", "mock_review_agent"),
                "task_preview": str(payload.get("task", ""))[:80],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
