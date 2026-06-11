---
name: date_normalize
description: Parse one date-related customer-message text file line by line and return yyyy-mm-dd dates joined with commas.
---

# date_normalize

Use this skill for customer-message date extraction and normalization tasks.

The skill reads the declared message text file, parses each line in order, and
returns one `yyyy-mm-dd` date per line joined by commas. It handles direct dates
with mixed separators, relative words such as yesterday/tomorrow/last week, day
and hour offsets, workday offsets, and year completion from context.

Call `skill_run` with:

```json
{
  "name": "date_normalize",
  "arguments": {
    "message_file": "<the declared txt file>"
  }
}
```

Return the `answer` field verbatim.
