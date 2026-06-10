---
name: mock_summary_skill
description: Mock skill that returns a fixed demo result.
---

# mock_summary_skill

This is a mock skill for demonstrating the skill lifecycle.

Use it when a demo question asks for `mock_summary_skill`. Load this file with
`skill_load`, then call `skill_run` with a JSON object containing `text`.
The executable returns a JSON string with `mock_result`.
