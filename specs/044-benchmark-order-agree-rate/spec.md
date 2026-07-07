# Spec 044 — order agree rate summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1112
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/agree_order_share.py`](../../benchmark/agree_order_share.py) (all-categorized agree share),
  [`benchmark/disagreement_outlook.py`](../../benchmark/disagreement_outlook.py) (disagreement rate telemetry)

This spec makes the **existing, implicit** order-agree-rate contract explicit. It describes the
as-built behavior of `benchmark/order_agree_rate.py`; it introduces **no behavior change**.

## Why

`agree_order_share` reports agree among all categorized judge outcomes; `order_agree_rate` reports
agree rate among dual-order tasks only (`agree / (agree + disagree + tie)`). Making its contract
explicit lets reviewers check order-agree-rate changes against intent.

## User stories

1. **As a benchmark operator**, I can read dual-order agree rate for judge-stability dashboards.
2. **As a CI maintainer**, I can log a stable `order_agree_rate_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_order_agree_rate(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Slice summary (`_slice_summary`)

- SHALL read `agree`, `disagree`, and `tie` from `judge_order_stats` when that value is a `dict`.
- WHEN `judge_order_stats` is not a `dict` THEN it SHALL be treated as empty (with a warning when
  non-`None`).
- WHEN every count is a non-negative `_is_int` THEN `total` SHALL be their sum.
- WHEN any count is invalid THEN all fields including `agree_rate` SHALL be `None`.
- WHEN all counts are valid and `total > 0` THEN `agree_rate` SHALL be `round(agree / total, 3)`.
- WHEN all counts are valid and `total == 0` THEN counts SHALL be `0` and `agree_rate` SHALL be
  `None`.

### Combined summary (`_combined`)

- WHEN both partition slices carry coherent `_is_int` values for `agree`, `disagree`, `tie`, and
  `total` THEN `_combined` SHALL sum counts and compute `agree_rate` on the totals.
- WHEN any field is missing or non-integer THEN `_combined` SHALL return all fields `None`.

### Artifact-kind branches (`summarize_order_agree_rate`)

Every summary SHALL include: `kind`, `agree`, `disagree`, `tie`, `total`, `agree_rate`,
`partitions`.

1. **`single` or `multi`** — top-level slice; `partitions` SHALL be `None`.
2. **`generalization`** — per-partition slices plus overall from `_combined(tuned, held_out)`.
3. **`invalid`** — rate and count fields `None`, `partitions` `None`.

### Order agree rate headline

- WHEN `total` is missing, not a non-negative `_is_int`, or `0` THEN the headline SHALL be
  exactly: `order agree rate: no dual-order stats available`.
- WHEN `kind == "generalization"` and `total > 0` THEN the headline SHALL include tuned and
  held-out partition rates in brackets.
- WHEN `total > 0` for other kinds THEN the headline SHALL be:
  `order agree rate: {rate_txt} ({agree}/{total})` where `rate_txt` uses percent formatting when
  `agree_rate` passes `_is_number`, otherwise `n/a`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_order_agree_rate()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_044_order_agree_rate.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_order_agree_rate.py`.
