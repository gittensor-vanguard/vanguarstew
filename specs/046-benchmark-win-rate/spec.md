# Spec 046 — win rate summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1124
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/decisive_rate.py`](../../benchmark/decisive_rate.py) (decisive versus tie shares),
  [`benchmark/judge_wlt.py`](../../benchmark/judge_wlt.py) (compact judge report),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification)

This spec makes the **existing, implicit** win-rate contract explicit. It describes the
as-built behavior of `benchmark/win_rate.py`; it introduces **no behavior change**.

## Why

`judge_wlt` reads the compact `judge_report` block; `win_rate` normalizes the underlying `tally`
counts into per-outcome rates for CI dashboards, with per-partition detail for a
`--generalization` artifact.

## User stories

1. **As a benchmark operator**, I can read challenger/baseline/tie rates from a replay tally.
2. **As a CI maintainer**, I can log a stable `win_rate_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_win_rate(artifact)` SHALL treat it
  as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Tally parsing (`_tally_counts`)

- SHALL read `challenger`, `baseline`, and `tie` from `slice_["tally"]` when `tally` is a `dict`.
- WHEN `tally` is missing or not a `dict` THEN `_tally_counts` SHALL return `None`.
- WHEN every count is a non-negative `_is_int` THEN `_tally_counts` SHALL return the triple.
- WHEN any count is invalid THEN `_tally_counts` SHALL return `None`.

### Slice summary (`_slice_summary`, `_rates`)

- WHEN `_tally_counts` returns `None` THEN `_slice_summary` SHALL return all count/rate fields
  as `None`.
- WHEN `total > 0` THEN each rate field SHALL be `round(count / total, 3)` for its outcome.
- WHEN `total == 0` THEN count fields SHALL be `0` and all rate fields SHALL be `None`.

### Artifact-kind branches (`summarize_win_rate`)

Every summary SHALL include: `kind`, `total`, `challenger`, `baseline`, `tie`, `challenger_rate`,
`baseline_rate`, `tie_rate`, `partitions`.

1. **`single` or `multi`** — top-level `_slice_summary(artifact)`; `partitions` SHALL be `None`.
2. **`generalization`** — per-partition `_slice_summary` for `tuned` and `held_out`; WHEN both
   slices carry `_is_int` `total` values THEN overall counts SHALL be summed and rates computed
   on the totals; OTHERWISE overall fields SHALL be `None`; `partitions` SHALL always include
   both partition slices.
3. **`invalid`** — top-level slice with all count/rate fields `None`; `partitions` SHALL be
   `None`.

### Win rate headline

- `_fmt_rate(value)` SHALL format as `f"{float(value):.1%}"` when `value` passes `_is_number`,
  otherwise `n/a`.
- WHEN `total` is missing, not a non-negative `_is_int`, or `0` THEN the headline SHALL be exactly:
  `win rate: no tally available`.
- WHEN `total > 0` THEN the headline SHALL be:
  `win rate: challenger {challenger}/{total} ({challenger_rate_txt}), baseline {baseline}, tie {tie}`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_win_rate()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_046_win_rate.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_win_rate.py`.
