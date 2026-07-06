# Spec 008 — the agent philosophy (`infer_philosophy()`)

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** agent
- **Issue:** #672
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/001-solve-contract`](../001-solve-contract/spec.md) (entrypoint seam),
  [`specs/007-agent-planner`](../007-agent-planner/spec.md) (planner consumes philosophy),
  [`specs/006-agent-decision`](../006-agent-decision/spec.md) (decider consumes philosophy)

This spec makes the **existing, implicit** philosophy contract explicit. It describes the
as-built behavior of `agent/philosophy.py`; it introduces **no behavior change**. The philosophy
step grounds downstream planning and decision-making — so its output shape and field
normalization must be written down and verified.

## Why

A malformed LLM field (`summary` as a number, `values` as a bare string, `evidence` as a list
with blanks) must not abort a replay run or leak arbitrary types into the planner/decider
prompts. The philosophy step already coerces these fields onto a stable shape; making that
contract explicit lets reviewers check philosophy changes against intent and gives M5 a
reviewable definition of the grounding surface.

## User stories

1. **As the planner/decider**, I receive a philosophy dict with normalized text and list fields
   — so downstream prompts never see arbitrary types.
2. **As an agent developer**, I know how malformed LLM output is mapped (non-dict → stub,
   bare string `values` → one-element list) — so I optimize real maintainer grounding, not
   prompt luck.
3. **As a reviewer**, philosophy normalization is written down — so a change to `philosophy.py`
   is checked against the spec.

## Acceptance criteria (EARS)

### Philosophy dict shape

- `infer_philosophy(context, llm)` SHALL return a `dict` containing at least `summary`,
  `values`, `merge_bar`, `direction`, and `evidence` when the LLM path runs (including
  offline stub).
- IF `context` is not a `dict` THEN `infer_philosophy()` SHALL return a minimal fallback
  (`summary` + `values`) without calling the LLM.
- IF the LLM returns a non-dict payload THEN `_normalize_philosophy()` SHALL fall back to the
  offline stub shape and still normalize every field.

### Text field normalization

- `summary`, `merge_bar`, and `direction` SHALL be coerced to `str`.
- WHEN a text field is `None` on input THEN normalization SHALL use the stub default for that
  field.
- Non-string scalars SHALL stringify.

### List field normalization

- `values` and `evidence` SHALL be coerced to `list[str]`.
- WHEN the model emits a bare string THEN the system SHALL wrap it as a one-element list
  (after strip); blank strings SHALL yield `[]`.
- WHEN the model emits a list THEN non-string/blank/`None` entries SHALL be skipped; remaining
  entries SHALL be stringified and stripped.
- WHEN a list field is any other type THEN the system SHALL return `[]`.

### Few-shot prompt contract

- The philosophy system prompt SHALL include at least one few-shot example demonstrating the
  expected JSON shape (`summary`, `values`, `merge_bar`, `direction`, `evidence`).
- Each few-shot example SHALL have non-empty `values` and `evidence` lists.

### Offline determinism

- WHEN the LLM is offline (`VANGUARSTEW_OFFLINE=1` / `api_key == "offline"`) THEN
  `infer_philosophy()` SHALL return the deterministic stub after normalization — exercisable in
  CI without a key.

### Robustness (per constitution)

- IF any LLM-emitted field has an unexpected type THEN normalization SHALL coerce or default,
  not raise — per `AGENTS.md` → *Benchmark integrity*.

## Out of scope

- **Planner / decider** output contracts — covered by specs 006–007.
- **Review-agent** contract — a separate path.
- Changing philosophy behavior — code changes follow the SDD loop in their own PRs; this spec
  documents the as-built surface only.

## Verification

- `tests/test_spec_008_philosophy.py` (this PR) exercises each EARS block against the real
  `infer_philosophy()` and normalization helpers.
- Broader unit coverage remains in `tests/test_philosophy.py`.
