---
name: sensitive_scan
description: Scan a nested archive (zip/tar, multi-level) for sensitive data counts - phone numbers, emails, ID-card numbers, API keys.
---

# sensitive_scan

Use this skill for the "compressed-archive sensitive information scan" question
(e.g. `sensitive_data_2_1.zip`). It does the heavy lifting deterministically:

1. Resolves and extracts the archive, recursing through nested `.tar` / `.zip`
   members (archives are detected by content, not just extension).
2. Counts sensitive items in every `.txt` / `.log` file with boundary-aware
   regex (total occurrences, NOT deduplicated):
   - phone: an `1`-led 11-digit number, bounded so it never matches a substring
     inside an 18-digit ID number
   - email: `user@domain.com`
   - ID card: 18 chars, 17 digits plus a trailing digit or `X`
   - API key: an `sk-` prefixed token
3. For images, transcribes the text via the model gateway (OCR) and applies the
   exact same regex to the transcription. If the model is not configured or the
   call fails, OCR is skipped gracefully and the text-only counts are returned
   with a warning (the skill never crashes).

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
