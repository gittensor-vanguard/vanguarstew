# Spec 040 — dual order share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1093
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/single_order_share.py`](../../benchmark/single_order_share.py) (single-presentation share),
  [`benchmark/dual_order_coverage.py`](../../benchmark/dual_order_coverage.py) (dual-order coverage vs tasks)

This spec makes the **existing, implicit** dual-order-share contract explicit. It describes the
as-built behavior of `benchmark/dual_order_share.py`; it introduces **no behavior change**.

## Why

`single_order_share` reports single-presentation outcomes; operators also need the fraction of
categorized judge outcomes that used dual presentation (`(agree + disagree + tie) / total`).
`summarize_dual_order_share()` is the reproducible read-only summary for CI dashboards.

## User stories

1. **As a benchmark operator**, I can read dual-presentation share before trusting judge stability
   metrics on a run that mixed single- and dual-order judging.
2. **As a CI maintainer**, I can log a stable `dual_order_share_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_dual_order_share(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline share
  formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Slice summary (`_slice_summary`)

- `_slice_summary` SHALL read all five `judge_order_stats` keys.
- `dual_order_tasks` SHALL be `agree + disagree + tie` when all counts are valid non-negative
  `_is_int` values.
- WHEN any count is invalid THEN the slice SHALL return
  `{"total": None, "dual_order_tasks": None, "dual_order_share": None}`.
- WHEN all counts are valid and `total > 0` THEN `dual_order_share` SHALL be
  `round(dual_order_tasks / total, 3)`.
- WHEN all counts are valid and `total == 0` THEN `total` SHALL be `0`, `dual_order_tasks` SHALL
  echo the dual count, and `dual_order_share` SHALL be `None`.

### Artifact-kind branches (`summarize_dual_order_share`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL include: `kind`, `total`, `dual_order_tasks`, `dual_order_share`, `partitions`.

1. **`single` or `multi`** — top-level fields from `_slice_summary(artifact)`; `partitions`
   SHALL be `None`.
2. **`generalization`** — per-partition slices under `partitions["tuned"]` and
   `partitions["held_out"]`; overall counts from summing both partitions' `total` and
   `dual_order_tasks` WHEN both carry coherent `_is_int` values; otherwise overall fields
   SHALL be `None`.
3. **`invalid`** — all count/share fields `None`, `partitions` `None`.

### Dual order share headline

- WHEN `total` is missing, not a non-negative `_is_int`, or `0` THEN the headline SHALL be
  exactly: `dual-order share: no judge stats available`.
- WHEN `total > 0` THEN the headline SHALL be:
  `dual-order share: {share_txt} ({dual_txt}/{total} categorized task(s))` where `share_txt`
  uses percent formatting when `dual_order_share` passes `_is_number`, otherwise `n/a`, and
  `dual_txt` is `str(dual_order_tasks)` when `dual_order_tasks` passes `_is_int`, otherwise
  `n/a`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_dual_order_share()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_040_dual_order_share.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_dual_order_share.py`.
