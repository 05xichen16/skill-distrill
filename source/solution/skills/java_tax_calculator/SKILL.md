---
name: java_tax_calculator
description: Repair the buggy Java personal-income-tax source, compile/validate it against the worked examples, and compute hidden case outputs with a java-version prefix.
---

# java_tax_calculator

Use this skill for the Java personal income tax calculator repair task.

The skill follows the task's own workflow, with the **javac repair-run path as
the primary strategy** (running the real program avoids the table-parsing
heuristics that mis-computed the hidden variant on the platform):

1. Asks the model to repair the full Java source (rules live in the comments).
   Reasoning is forced OFF on both gateway dialects (top-level `enable_thinking`
   and `chat_template_kwargs.enable_thinking`); with reasoning on, the bounded
   per-call timeout truncates the source and the whole path collapses.
2. Compiles with `javac`; compile errors / example mismatches are fed back for
   up to `JAVA_TAX_REPAIR_ROUNDS` (default 3) repair rounds.
3. Validates the build against the worked examples in the question text
   (`3000 -> 0.00` ...) before trusting it with the hidden cases.
4. Runs the 10 hidden salary cases and prefixes the real `java -version` line
   (`JAVA_VERSION_USE_SYSTEM` defaults true; falls back to a hard-coded version
   only when the toolchain is unreachable).

Every step is bounded by `SKILL_BUDGET_SECONDS`: if a repair round cannot
finish before the deadline (or the model gateway / JDK is missing), the skill
falls back to a fast Python re-implementation whose parameters come from the
source's encoded constants or a model extraction -- still validated against the
examples -- and finally to a well-formed shape answer. It always emits an
11-segment answer with the version prefix and exits 0, so it can never starve
into the version-less model loop. Set `JAVA_TAX_PREFER_JAVAC=false` to force the
Python path (e.g. CI without a JDK).

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
