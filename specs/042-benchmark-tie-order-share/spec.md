# Spec 042 — tie order share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1100
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/order_agree_rate.py`](../../benchmark/order_agree_rate.py) (dual-order agree rate)

This spec makes the **existing, implicit** tie-order-share contract explicit. It describes the
as-built behavior of `benchmark/tie_order_share.py`; it introduces **no behavior change**.

## Why

`order_agree_rate` reports agree rate among dual-order tasks only (`agree / (agree + disagree + tie)`).
`summarize_tie_order_share()` reports tie as a fraction of all categorized judge outcomes;
making its contract explicit lets reviewers check tie-order-share changes against intent.

## User stories

1. **As a benchmark operator**, I can read `tie / total` categorized tasks for judge-stability
   dashboards.
2. **As a CI maintainer**, I can log a stable `tie_order_share_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_tie_order_share(artifact)` SHALL
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

- `_slice_summary` SHALL read all five `judge_order_stats` keys: `agree`, `disagree`, `tie`,
  `single`, `offline`.
- WHEN every count is a non-negative `_is_int` THEN `total` SHALL be their sum and `tie` SHALL
  be the tie count.
- WHEN any count is invalid THEN the slice SHALL return
  `{"total": None, "tie": None, "tie_order_share": None}`.
- WHEN all counts are valid and `total > 0` THEN `tie_order_share` SHALL be
  `round(tie / total, 3)`.
- WHEN all counts are valid and `total == 0` THEN `total` SHALL be `0`, `tie` SHALL echo the
  tie count, and `tie_order_share` SHALL be `None`.

### Artifact-kind branches (`summarize_tie_order_share`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL include: `kind`, `total`, `tie`, `tie_order_share`, `partitions`.

1. **`single` or `multi`** — top-level fields from `_slice_summary(artifact)`; `partitions`
   SHALL be `None`.
2. **`generalization`** — per-partition slices under `partitions["tuned"]` and
   `partitions["held_out"]`; overall counts from summing both partitions' `total` and `tie`
   WHEN both carry coherent `_is_int` values; otherwise overall fields SHALL be `None`.
3. **`invalid`** — all count/share fields `None`, `partitions` `None`.

### Tie order share headline

- WHEN `total` is missing, not a non-negative `_is_int`, or `0` THEN the headline SHALL be
  exactly: `tie-order share: no judge stats available`.
- WHEN `total > 0` THEN the headline SHALL be:
  `tie-order share: {share_txt} ({tie_txt}/{total} categorized task(s))` where `share_txt`
  uses percent formatting when `tie_order_share` passes `_is_number`, otherwise `n/a`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_tie_order_share()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_042_tie_order_share.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_tie_order_share.py`.
