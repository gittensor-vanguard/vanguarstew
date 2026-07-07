# Spec 054 — component mix summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1165
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/composite_spread.py`](../../benchmark/composite_spread.py) (judge vs objective delta),
  [`benchmark/blend_weights.py`](../../benchmark/blend_weights.py) (configured blend weights),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification)

This spec makes the **existing, implicit** component-mix contract explicit. It describes the
as-built behavior of `benchmark/component_mix.py`; it introduces **no behavior change**.

## Why

`composite_spread` reports the delta between component means; `component_mix` normalizes them into
judge/objective fractions for CI dashboards, with per-partition detail for generalization artifacts.

## User stories

1. **As a benchmark operator**, I can read judge/objective blend fractions from `composite_parts`.
2. **As a CI maintainer**, I can log a stable `component_mix_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_component_mix(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Numeric semantics (`_is_number`, `_round3`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric.
- `_round3(value)` SHALL return `round(float(value), 3)` when numeric, otherwise `None`.

### Mix from parts (`_mix_from_parts`, `_slice_mix`)

- SHALL read `judge_mean` and `objective_mean` from `composite_parts` when that value is a `dict`.
- WHEN `composite_parts` is missing or not a `dict` THEN all fields SHALL be `None` (with a warning
  when non-`None` and non-dict).
- WHEN both means are numeric and their sum is non-zero THEN fractions SHALL be
  `round(mean / total, 3)`.
- WHEN either mean is invalid or the sum is zero THEN fraction fields SHALL be `None`.

### Artifact-kind branches (`summarize_component_mix`)

Every summary SHALL include: `kind`, `judge_mean`, `objective_mean`, `judge_fraction`,
`objective_fraction`, `partitions`.

1. **`single` or `multi`** — top-level `_slice_mix(artifact)`; `partitions` SHALL be `None`.
2. **`generalization`** — tuned and held-out partition mixes plus top-level fields from the tuned
   slice; `partitions` SHALL include both entries.
3. **`invalid`** — all telemetry fields `None`, `partitions` `None`.

### Component mix headline

- `_fmt_fraction(value)` SHALL format as `f"{float(value):.1%}"` when numeric, otherwise `n/a`.
- WHEN `kind == "generalization"` THEN the headline SHALL include overall and per-partition judge
  fractions in brackets.
- OTHERWISE the headline SHALL be: `component mix: judge {judge_fraction_txt}`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_component_mix()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_054_component_mix.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_component_mix.py`.
