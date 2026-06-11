---
name: prompt_learn_classify
description: Prompt-learning image classifier - learn the label set from a labelled training set, then classify every image of a validation set one-by-one against the task description. Generic across tasks; labels, class count and validation size are all derived from the inputs.
---

# prompt_learn_classify

Use this skill for "prompt-learning and reasoning" style questions: you are
given a **labelled training set** (images plus their labels) to learn the
classification rule from, and an **unlabelled validation set** whose images you
must classify one-by-one, emitting one labelled segment per image in order.

A clear signal you need this skill: the question's `files` declare **image
directories** (a training folder and a validation/test folder) rather than a
handful of inline images, and the task asks you to learn a rule from labelled
examples and apply it to every unlabelled image. Those directory images are
**not** attached to your context on purpose - this skill reads and classifies
them itself, one image at a time, so you must call it instead of trying to
answer from what you can see. Always pass the task description and let the skill
produce the full answer; do not classify the directory images yourself.

The skill is task-agnostic. It:

1. Discovers the label set dynamically from the training labels (deduplicated,
   order preserved) - it does not assume any particular labels or class count.
2. Walks the validation set in numeric order and classifies each image against
   the task description you pass in, calling the model gateway per image.
3. Normalises every model response to exactly one valid label (exact match,
   then longest-label substring match, then a deterministic fallback) so the
   output segments match the grader.
4. Never crashes on a single image and never drops a segment: a failing image
   gets the fallback label so the segment count and positions stay intact.
5. Emits the answer as `<i><LABEL>` joined by commas in numeric order, where
   `<i>` is the 1-based image index.

## How to call

Pass the question's task description verbatim, plus the training and validation
directory names exactly as they appear in the question's `files`:

```json
{
  "name": "prompt_learn_classify",
  "arguments": {
    "task_description": "<the question's task / classification rule, verbatim>",
    "train_dir": "<the training-set directory name from the question>",
    "val_dir": "<the validation-set directory name from the question>"
  }
}
```

The runner injects the question directory automatically, so relative directory
names are enough. `train_dir` / `val_dir` are optional and inferred from the
question's declared files when omitted. Add `"few_shot_k": <n>` only if you want
few-shot exemplars attached (default is zero-shot).

## What to return

The skill prints JSON like:

```json
{
  "answer": "1PASS,2FAIL,3NOT_INVOLVED,...",
  "predictions": [{"idx": 1, "label": "PASS"}, ...],
  "classes": ["PASS", "FAIL", "NOT_INVOLVED"],
  "val_total": 100, "ok": 100, "failed": 0, "fallback_used": 0,
  "accuracy": {"n": 20, "correct": 17, "acc": 0.85},
  "warnings": []
}
```

**Return the `answer` field verbatim** as the final answer for the question. Do
not classify the images yourself, and do not reorder or reformat the answer.
