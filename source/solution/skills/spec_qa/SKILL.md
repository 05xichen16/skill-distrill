---
name: spec_qa
description: Spec-grounded Q&A - answer several sub-questions about a fixed set of specification documents, one-by-one, using each spec's original wording and language, and return the answers joined by ';' in question order. Generic across tasks; question count, order, answers and per-question spec routing are all derived from the inputs.
---

# spec_qa

Use this skill for "read the specification documents and answer N sub-questions"
style questions: the question gives a fixed set of **specification / standard
documents** (a knowledge base) and asks several numbered sub-questions
(`Q1`, `Q2`, ...) whose answers must come from those documents. The answer is a
single string of the per-question answers joined by `;` in question order.

A clear signal you need this skill: the question declares a **documents folder**
(specs/standards) rather than inline content, the body lists multiple `Q<n>:`
sub-questions (often grouped under headers), and it demands that answers use the
documents' **original wording and original language** (even when a question is
asked in English) and be returned `;`-separated in `Q1..QN` order.

The skill is task-agnostic. It:

1. Parses the sub-questions and their order dynamically from the task
   description (and tracks each question's group header) - it does not assume a
   particular question count or order.
2. Routes each question to the relevant document by its group header / text, and
   retrieves the most relevant snippets from that document (falling back to
   searching across all documents when routing is ambiguous, so no question is
   dropped).
3. Asks the model each question separately against the retrieved snippet, under
   a hard constraint to answer **only** from the spec text, in its **original
   wording and language**, no translation, one line, no labels.
4. Joins the N answers with `;` **in code**, in question order, so the segment
   count is always exactly N and never drifts - any `;` inside an answer is
   neutralised so it cannot forge an extra segment.
5. Never crashes on a single question and never drops a segment: a question that
   cannot be answered gets a conservative placeholder so the segment count and
   positions stay intact.

## How to call

Pass the question text verbatim (it must include the full `Q<n>` list), plus the
documents directory name exactly as it appears in the question's declared files:

```json
{
  "name": "spec_qa",
  "arguments": {
    "task_description": "<the question text, verbatim, with the full Q list>",
    "spec_dir": "<the documents directory name from the question>"
  }
}
```

The runner injects the question directory automatically, so a relative
`spec_dir` is enough; `spec_dir` is optional and inferred from the question's
declared directory when omitted.

## What to return

The skill prints JSON like:

```json
{
  "answer": "<a1>;<a2>;...;<aN>",
  "per_question": [{"q": "Q1", "answer": "...", "source": "<doc>"}, ...],
  "n": 10,
  "warnings": []
}
```

**Return the `answer` field verbatim** as the final answer for the question. Do
not answer the sub-questions yourself, and do not reorder, reformat, translate
or re-split the answer.
