# Spec 006 — the agent decision (`decide()`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #629
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/001-solve-contract`](../001-solve-contract/spec.md) (entrypoint seam),
  [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md) (objective anchor consumes
  `version_bump`; decision-process judge reads `rationale`)

This spec makes the **existing, implicit** `decide()` contract explicit. It describes the
as-built behavior of `agent/decider.py`; it introduces **no behavior change**. The decider is
where a maintainer agent emits the **concrete call** (`action`, labels, reviewer, release bump,
optional patch) that both the objective anchor and the decision-process judge consume — so its
output shape and field normalization must be written down and verified.

## Why

A malformed LLM field (`action` as a list, `labels` as a bare string, `version_bump` as
`"NONE"`) must not abort a replay run or leak arbitrary free-text into scoring. The decider
already coerces these fields onto a stable vocabulary; making that contract explicit lets
reviewers check decider changes against intent and gives M5 a reviewable definition of the
decision surface.

## User stories

1. **As the validator**, I receive a decision dict with a normalized `action` from a fixed
   vocabulary — so objective scoring and the judge never see arbitrary verbs.
2. **As an agent developer**, I know how synonym/noise in LLM output is mapped (approve → merge,
   unknown → plan) — so I optimize real maintainer calls, not prompt luck.
3. **As a reviewer**, action/label/reviewer/bump/patch/rationale normalization is written down
   — so a change to `decider.py` is checked against the spec.

## Acceptance criteria (EARS)

### Decision dict shape

- `decide(context, philosophy, request, llm)` SHALL return a `dict` containing at least:
  `action`, `labels`, `reviewer`, `version_bump`, `patch`, `rationale`.
- Every returned key SHALL be present on every invocation (no absent keys); values MAY be
  `null`/`[]`/`""` when unused.
- IF the LLM returns a non-dict payload THEN `decide()` SHALL fall back to the offline stub
  shape and still normalize every field.

### Action normalization

- `action` SHALL be normalized onto `VALID_ACTIONS`:
  `merge`, `request-changes`, `reject`, `triage`, `assign-reviewer`, `release`, `plan`,
  `patch`, `close`, `label`.
- WHEN the model emits a known synonym (`approve`, `lgtm`, `request changes`, `closed`, …)
  THE system SHALL map it to the canonical verb.
- WHEN `action` is missing, blank, unknown, or a non-string THEN the system SHALL default to
  `plan` (never pass arbitrary free-text through to scoring).
- Normalization SHALL be case- and surrounding-whitespace-insensitive for string inputs.

### Labels normalization

- `labels` SHALL be coerced to `list[str]`.
- WHEN the model emits a bare string THEN the system SHALL wrap it as a one-element list
  (after strip); blank strings SHALL yield `[]`.
- WHEN the model emits a list THEN non-string/blank/`None` entries SHALL be skipped; remaining
  entries SHALL be stringified and stripped.
- WHEN `labels` is any other type THEN the system SHALL return `[]`.

### Reviewer normalization

- `reviewer` SHALL be coerced to `str | None`.
- A blank string SHALL become `None`.
- Numeric/bool scalars SHALL stringify; lists/dicts SHALL become `None`.

### Version bump normalization

- `version_bump` SHALL be coerced to one of `major`, `minor`, `patch`, or `None`.
- Nullish strings (`none`, `null`, `n/a`, blank) and unknown levels SHALL map to `None`.
- Non-string values SHALL map to `None`.
- Normalization SHALL be case-insensitive and match the scoring contract in
  `benchmark.score._norm_bump`.

### Patch normalization

- `patch` SHALL be coerced to `str | None`.
- A non-empty stripped string SHALL be kept; blank strings and non-strings SHALL become `None`.
- `patch` is intended for `action == "patch"`; the decider SHALL still coerce the field even
  when the action is something else (callers may ignore it).

### Rationale normalization

- `rationale` SHALL always be a string (never `None`); missing/`None` SHALL become `""`.
- Non-string values SHALL be stringified.

### Offline determinism

- WHEN the LLM is offline (`VANGUARSTEW_OFFLINE=1` / `api_key == "offline"`) THEN `decide()`
  SHALL return the deterministic stub (`action = plan`, empty labels, null reviewer/bump/patch,
  stub rationale) after normalization — exercisable in CI without a key.

### Robustness (per constitution)

- IF any LLM-emitted field has an unexpected type THEN normalization SHALL coerce or default,
  not raise — per `AGENTS.md` → *Benchmark integrity*.

## Out of scope

- **Planner / philosophy** output contracts — those are separate agent steps.
- **Review-agent** (`agent/review.py`) contract — a different path with its own shape.
- Changing decider behavior — code changes follow the SDD loop in their own PRs; this spec
  documents the as-built surface only.

## Verification

- `tests/test_spec_006_decision.py` (this PR) exercises each EARS block against the real
  `decide()` and normalization helpers.
- Broader unit coverage remains in `tests/test_decider.py`.
