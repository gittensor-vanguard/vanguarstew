# Spec 042 — offline share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1103
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/order_agree_rate.py`](../../benchmark/order_agree_rate.py) (dual-order agree rate)

This spec makes the **existing, implicit** offline-share contract explicit. It describes the
as-built behavior of `benchmark/offline_share.py`; it introduces **no behavior change**.

## Why

Replay artifacts may carry `judge_order_stats.offline` counts from stub judging.
`summarize_offline_share()` reports `offline / total` categorized outcomes for CI dashboards;
making its contract explicit lets reviewers check offline-share changes against intent.

## User stories

1. **As a benchmark operator**, I can read stub-judge share before trusting a replay headline.
2. **As a CI maintainer**, I can log a stable `offline_share_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_offline_share(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
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
- WHEN every count is a non-negative `_is_int` THEN `total` SHALL be their sum and `offline` SHALL
  be the offline count.
- WHEN any count is invalid THEN the slice SHALL return
  `{"total": None, "offline": None, "offline_share": None}`.
- WHEN all counts are valid and `total > 0` THEN `offline_share` SHALL be
  `round(offline / total, 3)`.
- WHEN all counts are valid and `total == 0` THEN `total` SHALL be `0`, `offline` SHALL echo the
  offline count, and `offline_share` SHALL be `None`.

### Artifact-kind branches (`summarize_offline_share`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL include: `kind`, `total`, `offline`, `offline_share`, `partitions`.

1. **`single` or `multi`** — top-level fields from `_slice_summary(artifact)`; `partitions`
   SHALL be `None`.
2. **`generalization`** — per-partition slices under `partitions["tuned"]` and
   `partitions["held_out"]`; overall counts from summing both partitions' `total` and `offline`
   WHEN both carry coherent `_is_int` values; otherwise overall fields SHALL be `None`.
3. **`invalid`** — all count/share fields `None`, `partitions` `None`.

### Offline share headline

- WHEN `total` is missing, not a non-negative `_is_int`, or `0` THEN the headline SHALL be
  exactly: `offline share: no judge stats available`.
- WHEN `total > 0` THEN the headline SHALL be:
  `offline share: {share_txt} ({offline_txt}/{total} categorized task(s))` where `share_txt`
  uses percent formatting when `offline_share` passes `_is_number`, otherwise `n/a`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_offline_share()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_042_offline_share.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_offline_share.py`.
