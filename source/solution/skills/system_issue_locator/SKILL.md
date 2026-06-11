---
name: system_issue_locator
description: Link frontend logs, HAR responses and backend validation logs to output module, failing interface and root causes.
---

# system_issue_locator

Use this skill for system defect location tasks that provide frontend logs,
backend validation logs, a HAR file and a validation schema.

The skill builds the foreground failure chain from the current files:

1. find the real foreground network request with visible/final UI failure;
2. read its path, actionId and validationRef from HAR;
3. collect validationCode values for that validationRef from backend logs;
4. map validation codes through `form_schema.json`;
5. output `module,path,rootCause1、rootCause2`.

Call `skill_run` with:

```json
{
  "name": "system_issue_locator",
  "arguments": {
    "source_dir": "<directory containing the logs, optional>"
  }
}
```

Return the `answer` field verbatim.
