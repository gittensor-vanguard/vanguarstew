# Spec 026 — disagreement outlook summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #874
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/judge_gate.py`](../../benchmark/judge_gate.py) (pass/fail judge robustness),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification)

This spec makes the **existing, implicit** disagreement-outlook contract explicit. It describes the
as-built behavior of `benchmark/disagreement_outlook.py`; it introduces **no behavior change**.

## Why

`judge_gate` pass/fails judge robustness; `summarize_disagreement_outlook()` exposes
`disagreement_rate` and `dual_order_tasks` for CI dashboards with a stable/unstable verdict.
Making its contract explicit lets reviewers check disagreement-outlook changes against intent.

## User stories

1. **As a benchmark operator**, I can read disagreement rate and dual-order task counts before
   trusting judge-stability dashboards.
2. **As a CI maintainer**, I can log a stable `disagreement_outlook_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling, partition aggregation, and every headline branch are
   written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_disagreement_outlook(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for rates, thresholds, and
  headline percent formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Judge telemetry selection (`_judge_telemetry`)

- `_judge_telemetry(slice_)` SHALL prefer `judge_report` over `judge_order_stats` when both are
  present as `dict` values.
- WHEN neither source is a `dict` THEN it SHALL return `{}`.

### Disagreement counts (`_disagreement_counts`)

- WHEN `dual_order_tasks` is a non-negative `_is_int` THEN it SHALL be used as the dual count.
- OTHERWISE WHEN `agree`, `disagree`, and `tie` are all non-negative `_is_int` values THEN
  `dual_order_tasks` SHALL be their sum.
- `disagreements` SHALL be read from `disagreements`, then `disagree`, then derived as
  `round(disagreement_rate * dual_order_tasks)` when the rate is numeric and dual is a valid int.
- WHEN disagreements or dual cannot be resolved as non-negative `_is_int` values THEN
  `_disagreement_counts` SHALL return `None`.

### Slice summary (`_slice_summary`)

- WHEN `_disagreement_counts` returns `None` THEN the slice SHALL return
  `{"dual_order_tasks": None, "disagreements": None, "disagreement_rate": None}`.
- WHEN telemetry carries a numeric `disagreement_rate` THEN the slice SHALL echo
  `round(rate, 3)`.
- WHEN telemetry omits a numeric rate and `dual_order_tasks == 0` THEN `disagreement_rate` SHALL be
  `None`.
- OTHERWISE `disagreement_rate` SHALL be `round(disagreements / dual_order_tasks, 3)`.

### Partition combination (`_combined`)

- Overall fields SHALL be `None` unless both partitions carry `_is_int` `dual_order_tasks` and
  `disagreements`.
- WHEN the summed dual count is `0` THEN overall counts SHALL be `0` and `disagreement_rate` SHALL
  be `None`.
- OTHERWISE overall `disagreement_rate` SHALL be `round(total_disagreements / total_dual, 3)`.

### Verdict (`_verdict`)

- WHEN the rate is not numeric THEN `_verdict` SHALL return `None`.
- WHEN the rate is numeric and `rate <= threshold` THEN `_verdict` SHALL return `"stable"`.
- WHEN the rate is numeric and `rate > threshold` THEN `_verdict` SHALL return `"unstable"`.

### Artifact-kind branches (`summarize_disagreement_outlook`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL include: `kind`, `dual_order_tasks`, `disagreements`, `disagreement_rate`,
`verdict`, `stable_threshold`, `partitions`.

- `stable_threshold` SHALL be `float(stable_threshold)` when the argument is numeric; otherwise
  `DEFAULT_STABLE_THRESHOLD` (`0.3`).

1. **`single` or `multi`** — top-level fields from `_slice_summary(artifact)`; `partitions` SHALL
   be `None`.
2. **`generalization`** — per-partition slices under `partitions["tuned"]` and
   `partitions["held_out"]`; overall fields from `_combined(tuned, held_out)`; overall `verdict`
   from the combined rate.
3. **`invalid`** — telemetry fields and `verdict` SHALL be `None`; `partitions` SHALL be `None`.

### Disagreement outlook headline

- `rate_txt` SHALL use percent formatting when `disagreement_rate` passes `_is_number`, otherwise
  `n/a`.
- `verdict` SHALL default to `"unknown"` when missing.
- `dual_txt` SHALL be the integer string when `dual_order_tasks` is a valid `_is_int`, otherwise
  `n/a`.
- For non-`generalization` summaries the headline SHALL be:
  `disagreement outlook: {verdict} (rate {rate_txt}, {dual_txt} dual-order task(s))`.
- For `generalization` summaries the headline SHALL append partition rates:
  `[tuned {tuned_txt}, held-out {held_txt}]` using the same percent/`n/a` rules per partition.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_disagreement_outlook()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_026_disagreement_outlook.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_disagreement_outlook.py`.
