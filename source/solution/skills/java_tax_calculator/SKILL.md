---
name: java_tax_calculator
description: Decode the Java personal-income-tax source parameters and compute hidden case outputs with java-version prefix.
---

# java_tax_calculator

Use this skill for the Java personal income tax calculator repair task.

The skill reads the declared Java source, decodes the triple-base64 tax bracket
table and deduction point, computes the hidden salaries from the question text,
and returns:

`<java-version-line>,<case1>,<case2>,...`

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
