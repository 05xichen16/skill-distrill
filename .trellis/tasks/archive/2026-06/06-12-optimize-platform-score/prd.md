# Optimize Contest Scoring From Platform Full Run

## Goal

Improve the contest solution after the latest platform full run. The platform scores show three high-impact failures: question 7 scored 0/9, question 9 scored 0/15, and question 4 scored 0.84/6. The local public scorer also shows Java tax and PO compliance as 0 or near-zero, so this task focuses on those deterministic failure paths first.

## What I Already Know

* Platform full-run scores: Q1 3.73/6, Q2 4.2/6, Q3 4.67/6, Q4 0.84/6, Q5 6/9, Q6 7.8/9, Q7 0/9, Q8 12.4/15, Q9 0/15, Q10 11.5/15.
* Public local score for `result.json` is 19.206/32:
  * `2_3` Java tax: 0.273/3, only the first tax value matched.
  * `3_2` PO compliance: 0/5, all-or-nothing exact match.
  * `1_4` interface: 2/2 locally, but weak on hidden platform variant.
* The likely platform mapping is:
  * Q4 -> interface test hidden variant.
  * Q7 -> Java tax calculator.
  * Q9 -> PO compliance audit.
  * Q8/Q10 are already relatively strong and should not be destabilized.
* Project constraints:
  * Python 3.9 compatible.
  * Standard library preferred; no new runtime dependencies unless unavoidable.
  * Answers must remain bare strings in grader-required format.

## Requirements

* Keep existing public-case behavior green or no worse for high-scoring tasks.
* Improve Java tax extraction so hidden variants do not depend on broken source execution or a model repair loop.
* Improve PO compliance so public exact answer is recoverable and hidden variants rely less on fragile keyword-only approval parsing.
* Improve interface hidden robustness by better deriving package id, auth, and step inference from input files.
* Keep runtime bounded for the 1-hour platform cap.

## Acceptance Criteria

* [ ] Public local scorer does not regress overall score.
* [ ] Java public case scores substantially above the current 0.273/3.
* [ ] PO public case matches the known public reference or produces a defensible improvement.
* [ ] Interface public case remains full score.
* [ ] Focused unit/regression tests pass for edited modules.

## Definition of Done

* Focused tests and public scorer are run.
* Any behavior changes are recorded in the final summary.
* No unrelated refactors or dependency churn.

## Technical Approach

* Treat low-scoring deterministic skills as the primary optimization surface.
* Prefer local parsing and executable validation where possible.
* Use model calls only for genuinely semantic judgments and protect them with structured output parsing plus code-side validation.

## Out of Scope

* Full rewrite of all skills.
* Adding OCR or image-processing dependencies.
* Chasing marginal score improvements for already high-scoring Q8/Q10 before fixing 0-score tasks.

## Technical Notes

* Relevant specs loaded:
  * `.trellis/spec/backend/index.md`
  * `.trellis/spec/backend/quality-guidelines.md`
  * `.trellis/spec/backend/error-handling.md`
  * `.trellis/spec/backend/directory-structure.md`
  * `.trellis/spec/guides/index.md`
  * `.trellis/spec/guides/code-reuse-thinking-guide.md`
* Relevant code inspected:
  * `source/solution/contestant_agent.py`
  * `source/solution/skills/java_tax_calculator/scripts/run.py`
  * `source/solution/skills/po_compliance_audit/scripts/run.py`
  * `source/solution/skills/interface_test/scripts/run.py`
  * `source/eval/score.py`
