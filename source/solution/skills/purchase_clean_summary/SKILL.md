---
name: purchase_clean_summary
description: Clean purchase orders using master data and attachment evidence, then summarize CNY totals for queries.
---

# purchase_clean_summary

Use this skill for purchase-data cleaning and query-total tasks.

The skill reads the declared purchase data directory, validates each PO against
vendor master data, category taxonomy and effective attachment evidence, then
outputs the `queries.csv` totals in query order. It can OCR image attachments
through the model gateway; when OCR is unavailable it degrades to text evidence
and system fields conservatively.

Call `skill_run` with:

```json
{
  "name": "purchase_clean_summary",
  "arguments": {
    "source_dir": "<declared purchase data directory>"
  }
}
```

Return the `answer` field verbatim.
