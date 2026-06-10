from __future__ import annotations

import json
import sys


def main() -> None:
    raw = sys.stdin.read().strip() or "{}"
    args = json.loads(raw)
    text = str(args.get("text", ""))
    print(
        json.dumps(
            {
                "mock_result": "mock-summary-skill-ok",
                "source": "mock_skill",
                "input_preview": text[:80],
            },
            ensure_ascii=False,
        )
    )


if __name__ == "__main__":
    main()
