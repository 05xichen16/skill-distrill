---
name: sensitive_scan
description: Scan a nested archive (zip/tar, multi-level) for sensitive data counts - phone numbers, emails, ID-card numbers, API keys.
---

# sensitive_scan

Use this skill for the "compressed-archive sensitive information scan" question
(e.g. `sensitive_data_2_1.zip`). It does the heavy lifting deterministically and
is hardened for the platform variant (same question text, different data):

1. Resolves and extracts the archive, recursing through nested `.zip`, `.tar`
   AND compressed members (`.tar.gz` / `.tgz` / `.gz` / `.bz2` / `.xz`).
   Containers are detected by content magic, not just extension.
2. Counts sensitive items in EVERY non-archive, non-image file (not only
   `.txt`/`.log` — the question says the archive may contain those file types
   "etc.") with boundary-aware regex (total occurrences, NOT deduplicated):
   - phone: an `1`-led 11-digit number, bounded so it never matches a substring
     inside an 18-digit ID number
   - email: `user@domain.<tld>` for any TLD (not only `.com`)
   - ID card: 18 chars, 17 digits plus a trailing digit or `X`
   - API key: an `sk-` prefixed token
3. For images (detected by extension or content magic), asks the multimodal
   model to transcribe ALL visible text verbatim, then counts tokens with the
   SAME regex used for text files — so image counts obey identical rules. If the
   model is unconfigured or a call fails, that image is skipped with a warning
   and the rest of the scan still returns (the skill never crashes). A
   wall-clock deadline (from `SKILL_BUDGET_SECONDS`) guarantees a well-formed
   answer is emitted before the runner's kill timeout.

## How to call

Call `skill_run` with:

```json
{ "name": "sensitive_scan", "arguments": { "zip_path": "<the zip declared in the question>" } }
```

The runner injects the question directory automatically, so a relative
`zip_path` (the name from the question's `files`) is enough.

## What to return

The skill prints JSON like:

```json
{
  "answer": "2806,3495,2328,3591",
  "breakdown": { "text": [...], "image": [...], "total": [...] },
  "images_total": 6,
  "images_ocr_ok": 6,
  "warnings": []
}
```

**Return the `answer` field verbatim** as the final answer for the question
(format: `phone,email,id,apikey`). Do not re-count or reformat it yourself.
