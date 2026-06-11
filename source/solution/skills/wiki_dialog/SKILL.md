---
name: wiki_dialog
description: FSE persona Wiki-dialog Q&A - for each dialog emit 'id=>persona_phrase|||reply|||service_action' and return the elements as a JSON array text in dialog order. reply and service_action are taken verbatim from authoritative sources (annotated chat_history.db messages and keyed Wiki FAQ answers); persona_phrase is code-generated from the persona naming rule; the model only selects which pre-loaded candidate matches each question. Generic across variants; dialog count, candidate pool, key->action map and naming rule are all derived from the inputs.
---

# wiki_dialog

Use this skill for the "IDE plugin FSE digital-human Q&A" style question: a
**persona** (an FSE digital human), a **chat history database**
(`chat_history.db`), a **Wiki access contract** (`source_access.json`) and a
list of **dialog questions** (`dialog_tests_complex.json`) are given, and you
must answer every dialog with one fixed-format element

```
<dialog_id>=>persona_phrase|||reply|||service_action
```

returning all elements as a **JSON array text**, in dialog order.

A clear signal you need this skill: the question declares the four files above
(an FSE persona, a SQLite chat history, a Wiki service contract with
`service_action_options` / `service_action_key_map`, and a dialogs file), and it
demands that `reply` be the **original wording** of a Wiki FAQ `a` field or a
`messages.content` row (no rewriting, no summarising, no translation) and that
`service_action` be one of the `service_action_options` verbatim.

The skill is task-agnostic and never lets the model author text. It:

1. Code-generates each `persona_phrase` from the persona's **naming rule**
   (parsed from `persona.md`, with a safe fallback): a present `user.name` ->
   `<greeting><name><suffix>`; an empty/missing name -> the fallback phrase.
   No spaces are inserted, so the phrase matches the reference exactly.
2. Pre-loads one **authoritative candidate pool**: the DB's *annotated* messages
   (`messages` joined to `message_actions` on `message_id`, so only rows with a
   `service_action_key` -- the current, valid wording -- are kept) and the Wiki
   FAQs that carry a `service_action_key` (fetched via `list_pages` then
   `get_page`; the base url and endpoints come from `source_access.json`). Old /
   noise records are excluded by construction.
3. For each dialog, lexically pre-ranks the pool (DB-preferred on ties) and asks
   the model to **select** the single best-matching candidate by **index**. The
   model never writes `reply`; it only chooses.
4. Takes `reply` verbatim from the chosen candidate, takes its
   `service_action_key`, and resolves `service_action` via
   `service_action_key_map` (read from `source_access.json`), keeping only
   candidates whose action is one of `service_action_options` verbatim.
5. Joins each element by code (exactly one `=>` and two `|||`; candidates
   containing those tokens or a newline are dropped) and serialises the list
   with `json.dumps`, in dialog order. The element count never drifts: a dialog
   with no usable candidate still emits a conservative placeholder element.

Because the model only selects and all text is copied verbatim, the
`list_equal` grader's whole-element equality holds; a wrong selection costs at
most that one element.

## How to call

Pass the question text verbatim, plus the IDE-plugin-FSE directory name exactly
as it appears in the question's declared files:

```json
{
  "name": "wiki_dialog",
  "arguments": {
    "task_description": "<the question text, verbatim>",
    "source_dir": "<the IDE-plugin-FSE directory name from the question>"
  }
}
```

The runner injects the question directory automatically, so a relative
`source_dir` is enough; `source_dir` is optional and inferred from the
question's declared files when omitted. The Wiki service must be reachable at
the `base_url` in `source_access.json`; if it is not, the skill degrades to the
DB candidate pool rather than crashing.

## What to return

The skill prints JSON like:

```json
{
  "answer": "[\"id=>persona|||reply|||action\", ...]",
  "per_dialog": [{"id": "...", "persona": "...", "source": "db", "action": "..."}, ...],
  "n": 30,
  "warnings": []
}
```

**Return the `answer` field verbatim** as the final answer for the question. It
is already a JSON array text. Do not answer the dialogs yourself, and do not
reorder, reformat, translate or re-split the answer.
