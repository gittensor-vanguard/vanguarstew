# Spec 045 — decisive rate summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1119
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/win_rate.py`](../../benchmark/win_rate.py) (per-outcome tally rates),
  [`benchmark/judge_wlt.py`](../../benchmark/judge_wlt.py) (compact judge report),
  [`benchmark/order_agree_rate.py`](../../benchmark/order_agree_rate.py) (dual-order agree rate)

This spec makes the decisive-rate contract explicit. It describes the behavior of
`benchmark/decisive_rate.py`, including summing the `tuned` / `held_out` partitions for a
`--generalization` artifact so the overall rate is reported instead of `n/a` (mirroring
`win_rate`; see #1154).

## Why

`win_rate` reports challenger/baseline/tie rates separately; `decisive_rate` reports how often
judging produced a decisive winner (`challenger + baseline`) versus a tie — useful for spotting
memorized-tie artifacts in CI dashboards, with per-partition detail for a `--generalization`
artifact.

## User stories

1. **As a benchmark operator**, I can read decisive versus tie task shares from a replay tally.
2. **As a CI maintainer**, I can log a stable `decisive_rate_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_decisive_rate(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Tally parsing (`_tally_counts`)

- SHALL read `challenger`, `baseline`, and `tie` from `artifact["tally"]` when `tally` is a `dict`.
- WHEN `tally` is missing or not a `dict` THEN `_tally_counts` SHALL return `None`.
- WHEN every count is a non-negative `_is_int` THEN `_tally_counts` SHALL return the triple.
- WHEN any count is invalid THEN `_tally_counts` SHALL return `None`.

### Decisive rate summary (`summarize_decisive_rate`)

Every summary SHALL include: `kind`, `total`, `decisive`, `tie`, `decisive_rate`, `tie_share`,
`partitions`. A single slice's `_slice_summary` reads its tally as: all fields `None` when
`_tally_counts` returns `None`; `decisive` = `challenger + baseline`, `tie` the tally tie count,
`decisive_rate` = `round(decisive / total, 3)`, and `tie_share` = `round(tie / total, 3)` when
`total > 0`; and count fields `0` with `None` rates when `total == 0`.

The `kind` (from `benchmark.comparability.artifact_kind`) selects the slice:

1. **`single` / `multi` / `invalid`** — top-level slice from the artifact's own tally;
   `partitions` SHALL be `None`.
2. **`generalization`** — per-partition slices for `tuned` and `held_out`; WHEN both carry an
   `_is_int` `total` THEN overall counts SHALL be summed and rates computed on the totals;
   OTHERWISE overall fields SHALL be `None`; `partitions` SHALL always include both slices.

### Decisive rate headline

- `_fmt_rate(value)` SHALL format as `f"{float(value):.1%}"` when `value` passes `_is_number`,
  otherwise `n/a`.
- WHEN `total` is missing, not a non-negative `_is_int`, or `0` THEN the headline SHALL be exactly:
  `decisive rate: no tally available`.
- WHEN `total > 0` THEN the headline SHALL be:
  `decisive rate: {decisive}/{total} ({decisive_rate_txt}), tie {tie} ({tie_share_txt})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_decisive_rate()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_045_decisive_rate.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_decisive_rate.py`.
