# Spec 047 — dual-order coverage summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1127
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/dual_order_share.py`](../../benchmark/dual_order_share.py) (dual-order task share),
  [`benchmark/single_order_share.py`](../../benchmark/single_order_share.py) (single-order task share)

This spec makes the **existing, implicit** dual-order-coverage contract explicit. It describes the
as-built behavior of `benchmark/dual_order_coverage.py`; it introduces **no behavior change**.

## Why

Dual-order judging is the robust path; single-order judging is cheaper but higher variance.
`summarize_dual_order_coverage()` reports `dual_order_tasks / tasks` so dashboards can see how
much of a run relied on the robust treatment versus cheaper single-order judging.

## User stories

1. **As a benchmark operator**, I can read dual-order judging coverage from a replay artifact.
2. **As a CI maintainer**, I can log a stable `dual_order_coverage_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_dual_order_coverage(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Ratio semantics (`_is_ratio`)

- Only non-boolean `int`/`float` values SHALL count as ratios for headline percent formatting.
- `bool` SHALL NOT be treated as a ratio.

### Count extraction (`_dual_order_tasks`, `_task_total`)

- `_dual_order_tasks` SHALL read `dual_order_tasks` from `slice_["judge_order_stats"]` when stats is
  a `dict`.
- `_task_total` SHALL read the top-level `tasks` from the slice when it is a non-negative
  `_is_int`; otherwise it SHALL sum `per_repo[*].tasks` (a multi-repo run and each generalization
  partition carry no top-level `tasks`), returning `None` when `per_repo` is not a non-empty list
  or any entry lacks a non-negative `_is_int` `tasks`.
- WHEN a count is missing, not a non-negative `_is_int`, or stats is not a `dict` THEN the helper
  SHALL return `None`.

### Coverage ratio (`_coverage`)

- WHEN `dual` or `total` is `None`, `total == 0`, or `dual > total` THEN `_coverage` SHALL return
  `None` (not clamp).
- WHEN counts are valid and `total > 0` THEN `_coverage` SHALL return `round(dual / total, 3)`.

### Slice coverage (`_slice_coverage`)

- SHALL return `dual_order_tasks`, `tasks`, and `coverage` from a slice via the helpers above.
- Non-dict slices SHALL be coerced via `_dict`.

### Combined coverage (`_combined`)

- WHEN every slice carries `_is_int` values for both `dual_order_tasks` and `tasks` THEN `_combined`
  SHALL sum counts and compute coverage from the totals.
- WHEN any slice lacks integer counts THEN `_combined` SHALL return all fields `None`.

### Artifact-kind branches (`summarize_dual_order_coverage`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL include: `kind`, `dual_order_tasks`, `tasks`, `coverage`, `partitions`.

1. **`single` or `multi`** — top-level fields from `_slice_coverage(artifact)`; `partitions`
   SHALL be `None`.
2. **`generalization`** — per-partition slices under `partitions["tuned"]` and
   `partitions["held_out"]`; overall counts from `_combined(tuned, held_out)`.
3. **`invalid`** — all count/coverage fields `None`, `partitions` `None`.

### Dual-order coverage headline

- `_is_ratio(coverage)` SHALL gate percent formatting; otherwise coverage text SHALL be `n/a`.
- WHEN both `dual_order_tasks` and `tasks` are non-negative `_is_int` values THEN the headline SHALL
  be: `dual-order coverage: {coverage_txt} ({dual}/{total} tasks judged in both orders)`.
- OTHERWISE the headline SHALL be: `dual-order coverage: {coverage_txt}`.
- Non-dict summaries SHALL be coerced via `_dict` (not raise).

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_dual_order_coverage()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_047_dual_order_coverage.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_dual_order_coverage.py`.
