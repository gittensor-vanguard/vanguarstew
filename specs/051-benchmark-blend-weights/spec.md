# Spec 051 — blend weights summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1156
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/score_integrity.py`](../../benchmark/score_integrity.py) (composite weight verification),
  [`benchmark/composite_spread.py`](../../benchmark/composite_spread.py) (headline partition reads),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification)

This spec makes the **existing, implicit** blend-weights contract explicit. It describes the
as-built behavior of `benchmark/blend_weights.py`; it introduces **no behavior change**.

## Why

`score_integrity` verifies the composite matches its weights, but nothing exposes the weights
themselves as a compact JSON summary for CI logs. `summarize_blend_weights` reads the `weights`
dict from the headline partition.

## User stories

1. **As a benchmark operator**, I can read judge/objective blend weights from a replay artifact.
2. **As a CI maintainer**, I can log a stable `blend_weights_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_blend_weights(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Numeric semantics (`_is_number`)

- Only **finite**, non-boolean `int`/`float` values SHALL count as numeric; a `NaN`/`Infinity`
  weight (which `json` round-trips verbatim) SHALL NOT, so it degrades to `None`/`unavailable`
  rather than poisoning the reported `sum` (mirrors `component_mix` / `composite_spread`).
- `bool` SHALL NOT be treated as numeric.

### Headline partition (`_headline_partition`)

- WHEN both `tuned` and `held_out` are `dict` values THEN `_headline_partition` SHALL return
  `tuned`.
- OTHERWISE it SHALL return the top-level artifact dict.

### Blend weights summary (`summarize_blend_weights`)

Every summary SHALL include: `kind`, `judge`, `objective`, `sum`.

- `kind` SHALL come from `artifact_kind(artifact)`.
- SHALL read `weights` from the headline partition.
- WHEN `weights` is not a `dict` THEN all weight fields SHALL be `None` (with a warning when
  non-`None` and non-dict).
- WHEN `judge` and `objective` pass `_is_number` THEN they SHALL be returned as `float` values and
  `sum` SHALL be `round(judge + objective, 3)`.
- WHEN either weight is invalid THEN `judge`, `objective`, and `sum` SHALL be `None`.

### Blend weights headline

- WHEN either `judge` or `objective` is `None` THEN the headline SHALL be exactly:
  `blend weights: unavailable`.
- OTHERWISE the headline SHALL be:
  `blend weights: judge {judge}, objective {objective} (sum {sum})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_blend_weights()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_051_blend_weights.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_blend_weights.py`.
