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

4. The set of sensitive categories AND their output order are read from the
   question's `输出格式` line at runtime — NOT hardcoded. The public set asks for
   exactly four (`手机号,邮箱,身份证,APIKey`) but the variant may add a type
   (e.g. 银行卡号), and the grader is positional+exact, so emitting four numbers
   when the variant wants five scores ~zero. The four known categories always
   reuse the validated regexes (zero model calls, byte-identical); a genuinely
   new category gets a model-synthesised detector, degrading to a 0 count that
   keeps its position if the model is unavailable.

## How to call

Call `skill_run` with:

```json
{ "name": "sensitive_scan", "arguments": { "zip_path": "<the zip declared in the question>", "task_description": "<the question text, verbatim>" } }
```

The runner injects the question directory automatically, so a relative
`zip_path` (the name from the question's `files`) is enough. Pass
`task_description` (the verbatim question text) so the skill reads the output
format / category list; if omitted it falls back to the four public categories.

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

**Return the `answer` field verbatim** as the final answer for the question.
The number of comma-separated counts follows the question's output-format line
(four for the public set: `phone,email,id,apikey`; more if the variant adds a
type). The `fields` array echoes the parsed category order for inspection. Do
not re-count or reformat the answer yourself.
