# Spec 009 — the agent review (`review_pr()`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #689
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/001-solve-contract`](../001-solve-contract/spec.md) (entrypoint seam),
  [`specs/006-agent-decision`](../006-agent-decision/spec.md) (parallel action vocabulary),
  [`REVIEW.md`](../../REVIEW.md) (maintainer rubric and the `perf:*`/`mult:contribution`
  value labels)

This spec makes the **existing, implicit** review contract explicit. It describes the as-built
behavior of `agent/review.py`; it introduces **no behavior change**. The review step applies
maintainer judgment to live pull requests and maps output onto the project's review rubric — so
its output shape and field normalization must be written down and verified.

## Why

A malformed LLM field (`action` as a list, `concerns` as a bare string, `value_label` as free
text, `files` as a truthy non-list) must not abort a maintainer-assist run or leak arbitrary
types into triage. The review agent already coerces these fields onto a stable vocabulary;
making that contract explicit lets reviewers check review changes against intent.

## User stories

1. **As a maintainer-assist caller**, I receive a review dict with normalized `action` from a
   fixed vocabulary and a canonical value label — so triage never sees arbitrary verbs or
   unknown tiers.
2. **As an agent developer**, I know how synonym/noise in LLM output is mapped (`approve` →
   `merge`, unknown action → `comment`) — so I optimize real maintainer reviews, not prompt luck.
3. **As a reviewer**, action/value-label/bool/text/concerns normalization is written down — so a
   change to `review.py` is checked against the spec.

## Acceptance criteria (EARS)

### Review dict shape

- `review_pr(pr, philosophy, llm)` SHALL return a `dict` containing at least: `action`,
  `value_label`, `scope_ok`, `tests_present`, `summary`, `concerns`, `recommendation`.
- Every returned key SHALL be present on every invocation; values SHALL use the normalized types
  below.
- IF `pr` is not a `dict` THEN `review_pr()` SHALL return a fixed error dict (`action =
  comment`, explanatory `summary`/`recommendation`) without calling the LLM.
- IF the LLM returns a non-dict payload THEN `_normalize_review()` SHALL fall back to the offline
  stub shape and still normalize every field.

### Action normalization

- `action` SHALL be normalized onto `ACTIONS`: `merge`, `request-changes`, `reject`, `comment`.
- WHEN the model emits a known synonym (`approve`, `lgtm`, `request changes`, `decline`, …) THE
  system SHALL map it to the canonical verb.
- WHEN `action` is missing, blank, unknown, or a non-string THEN the system SHALL default to
  `comment` (never pass arbitrary free-text through to triage).
- Normalization SHALL be case- and surrounding-whitespace-insensitive for string inputs.

### Value-label normalization

- `value_label` SHALL be coerced to one of `VALUE_LABELS` (`perf:pending`,
  `mult:contribution`). This field is advisory only — `review_pr()` reads a diff, it never
  runs a benchmark, so it can flag whether a PR is on the measured `agent/` surface
  (`perf:pending`) or the flat-rate one (`mult:contribution`), but it can NOT predict a
  `perf:xs`–`perf:xl` band; that requires an actual before/after
  `scripts/score_pr_delta.py` run (see REVIEW.md).
- WHEN the model emits a near-miss form (missing prefix, underscores, spaces, mixed case)
  THE system SHALL map it to the matching canonical tier.
- WHEN `value_label` is blank, unknown (including a retired tier like the old `mult:*`
  ladder), or a non-string THEN the system SHALL default to `mult:contribution`.

### Boolean normalization

- `scope_ok` and `tests_present` SHALL be coerced to `bool`.
- String inputs SHALL treat `true`, `yes`, and `1` (case-insensitive, stripped) as true; other
  non-empty strings as false.
- Integer and float inputs SHALL use Python truthiness.
- WHEN a bool field is any other type THEN the system SHALL use the stub default for that field.

### Text normalization

- `summary` and `recommendation` SHALL be coerced to `str`.
- WHEN a text field is `None` THEN normalization SHALL return `""`.
- Non-string scalars SHALL stringify.

### Concerns normalization

- `concerns` SHALL be coerced to `list[str]`.
- WHEN the model emits a bare string THEN the system SHALL wrap it as a one-element list (after
  strip); blank strings SHALL yield `[]`.
- WHEN the model emits a list THEN non-string/blank/`None` entries SHALL be skipped; remaining
  entries SHALL be stringified and stripped.
- WHEN `concerns` is any other type THEN the system SHALL return `[]`.

### PR files input

- The `files` field on `pr` SHALL contribute to the offline stub's `tests_present` only when it
  is a `list` containing at least one non-blank string path starting with `tests/`.
- A truthy non-list `files` value SHALL be treated as no files (must not abort review).
- Non-string entries inside a list SHALL be skipped.

### Offline determinism

- WHEN the LLM is offline (`VANGUARSTEW_OFFLINE=1` / `api_key == "offline"`) THEN `review_pr()`
  SHALL return the deterministic stub (`action = comment`, stub summary/recommendation,
  `concerns = []`) after normalization, with `tests_present` derived from visible `tests/`
  paths in the PR, and `value_label` derived from visible `agent/` paths (`perf:pending` if
  the PR touches `agent.py` or `agent/`, else `mult:contribution`) — exercisable in CI
  without a key.

### Robustness (per constitution)

- IF any LLM-emitted field has an unexpected type THEN normalization SHALL coerce or default,
  not raise — per `AGENTS.md` → *Benchmark integrity*.

## Out of scope

- **CLI fetching** (`scripts/review_pr.py`) — covered by `tests/test_review_pr.py`.
- **Decider / planner / philosophy** contracts — separate agent steps.
- Changing review behavior — code changes follow the SDD loop in their own PRs; this spec
  documents the as-built surface only.

## Verification

- `tests/test_spec_009_review.py` (this PR) exercises each EARS block above against the real
  `review_pr()` and normalization helpers.
- Broader unit coverage remains in `tests/test_review.py`.
