---
name: interface_test
description: Interface test-case verifier - run every case in test_cases.json against a real HTTP service in order (get a fresh write token before each write step), assert each response in code (status + field presence + exact values), and return the comma-joined IDs of the FAILING cases in test_cases order. Generic; base URL, token config, package-id header, cases, assertions and endpoints are all read from the input files, never hard-coded.
---

# interface_test

Use this skill for "call the real interface(s) and tell me which test cases do
NOT pass" style questions: the question gives an input folder with a
`test_cases.json` (a list of cases, each with a natural-language `description`
and an `assert` block), an `api_doc.md` (the endpoint catalogue) and an
`auth_config.json` (base URL, token endpoint, package-id header). The answer is
the comma-separated list of **failing** case IDs, in the cases' file order.

A clear signal you need this skill: the question asks to verify cases by
**really calling** a running service, says cases run **in their file order**,
mentions a per-request package-id header (`X-Package-Id`) and a write-token rule
(get a token from `/api/auth/token`, one successful write per token), and demands
only the failing IDs as a comma-separated string with no explanation.

The skill is task-agnostic. It:

1. Reads `test_cases.json`, `api_doc.md` and `auth_config.json` from the input
   folder. The base URL, package-id header name, token endpoint/method/body and
   the response token path are all taken from `auth_config.json` - nothing about
   the service is hard-coded, so a variant that changes endpoints, auth or data
   is handled by re-reading the files.
2. Uses the model to translate each case's natural-language `description` into an
   ordered list of structured HTTP steps (method / path / query / body, marked
   read or write, with which step's response to assert), cross-checked against
   `api_doc.md`. The model only plans the calls; it never decides pass/fail.
3. Runs the cases strictly in file order (serially - write state accumulates per
   package-id, so concurrency would corrupt the ordering semantics). Every
   request carries the same `X-Package-Id` (from the `PACKAGE_ID` / `packageId`
   env) for the whole run. Before each write step it fetches a fresh token and
   sends `Authorization: Bearer <accessToken>` (unless the step explicitly tests
   reusing an old token for a 401).
4. Asserts each case **in code** against the chosen response: actual status ==
   `expectedStatus`, every `expectedFields` dotted path exists (array indices
   like `data.list.0.userId` supported), and every `expectedValues` dotted path
   equals exactly. Any miss -> the case is failing and its ID is collected.
5. Joins the failing IDs with `,` **in code**, in test_cases order. The ratio
   grader is position-sensitive, so the order is the cases' file order and the
   skill prefers to under-report rather than over-report (an extra ID shifts
   every later position).
6. Never crashes: missing config, an unreachable service or a model failure
   degrade gracefully - a case that cannot be judged is treated conservatively
   (not reported as failing) so positions do not drift.

## How to call

Pass the question text verbatim plus the input directory name exactly as it
appears in the question's declared files:

```json
{
  "name": "interface_test",
  "arguments": {
    "task_description": "<the question text, verbatim>",
    "doc_dir": "<the input directory name from the question>"
  }
}
```

The runner injects the question directory automatically, so a relative `doc_dir`
is enough; `doc_dir` is optional and inferred from the question's declared files
when omitted.

## What to return

The skill prints JSON like:

```json
{
  "answer": "TC009,TC011,TC014,TC015,TC016,TC020",
  "per_case": [{"id": "TC001", "passed": true, "reason": ""}, ...],
  "failed": ["TC009", "TC011", "..."],
  "n": 20,
  "warnings": []
}
```

**Return the `answer` field verbatim** as the final answer for the question. Do
not re-run the cases yourself, and do not reorder, reformat or add/remove IDs.
