---
name: java_tax_calculator
description: Repair the buggy Java personal-income-tax source, compile/validate it against the worked examples, and compute hidden case outputs with a java-version prefix.
---

# java_tax_calculator

Use this skill for the Java personal income tax calculator repair task.

The skill follows the task's own workflow:

1. Asks the model to repair the full Java source (rules live in the comments).
2. Compiles with `javac`; compile errors / example mismatches are fed back for
   up to `JAVA_TAX_REPAIR_ROUNDS` (default 3) repair rounds.
3. Validates the build against the worked examples in the question text
   (`3000 -> 0.00` ...) before trusting it with the hidden cases.
4. Runs the 10 hidden salary cases and prefixes the real `java -version` line.

When no JDK is available or repair rounds are exhausted it falls back to a
Python re-implementation whose parameters come from the source's encoded
constants or a model extraction -- still validated against the examples.

Call `skill_run` with:

```json
{
  "name": "java_tax_calculator",
  "arguments": {
    "task_description": "<question text>",
    "source_file": "<declared .java file>"
  }
}
```

Return the `answer` field verbatim.
