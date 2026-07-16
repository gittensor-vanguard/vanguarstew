# Spec 052 — gap outlook summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1160
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/acceptance.py`](../../benchmark/acceptance.py) (generalization gap gate),
  [`benchmark/trend.py`](../../benchmark/trend.py) (headline score fallback),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification)

This spec makes the gap-outlook contract explicit. It describes the behavior of
`benchmark/gap_outlook.py`, including recomputing the gap from partition composites rather than
trusting a possibly-stale top-level field (mirroring `check_generalization`).

## Why

`acceptance` gates whether the generalization gap is within a bound; `gap_outlook` only reports
the gap, partition headline scores, and whether held-out performance held up versus tuned (a
`favorable` verdict when `generalization_gap <= 0`, matching the gap sign used by `acceptance`).

## User stories

1. **As a benchmark operator**, I can read generalization gap outlook from a tuned/held-out artifact.
2. **As a CI maintainer**, I can log a stable `gap_outlook_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_gap_outlook(artifact)` SHALL treat it
  as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Numeric semantics (`_is_number`)

- Only non-boolean `int`/`float` values SHALL count as numeric.
- `bool` SHALL NOT be treated as numeric.

### Partition score (`_partition_score`)

- WHEN `scored_repos` is numeric and zero (including `0.0`, not `bool`) THEN `_partition_score`
  SHALL return `None`.
- WHEN `composite_mean` passes `_is_number` THEN `_partition_score` SHALL return
  `round(float(composite_mean), 3)`.
- OTHERWISE `_partition_score` SHALL return `None`.

### Gap outlook summary (`summarize_gap_outlook`)

Every summary SHALL include: `kind`, `generalization_gap`, `tuned_score`, `held_out_score`,
`verdict`.

- WHEN `kind != "generalization"` THEN all telemetry fields SHALL be `None`.
- WHEN `kind == "generalization"` THEN `generalization_gap` SHALL be
  `round(tuned_composite - held_out_composite, 3)` when both partition composites are available
  (via `_partition_score`), otherwise `None`. The top-level ``generalization_gap`` field is
  ignored when recomputing (mirroring ``check_generalization``), so a stale value cannot flip
  the verdict.
- `tuned_score` SHALL be `_partition_score(tuned)` when that returns a number, otherwise
  `headline_score(tuned)`.
- `held_out_score` SHALL be `_partition_score(held_out)`.
- WHEN `generalization_gap` is numeric THEN `verdict` SHALL be `"favorable"` if `gap <= 0`, else
  `"unfavorable"`; otherwise `verdict` SHALL be `None`. (`generalization_gap = tuned - held_out`,
  so a positive gap means held-out performance dropped relative to tuned — worse generalization —
  consistent with the sign used by `acceptance`, `runner`, and `gap_integrity`.)

### Gap outlook headline

- WHEN `kind != "generalization"` THEN the headline SHALL be exactly:
  `gap outlook: not a generalization artifact`.
- `gap_txt` SHALL be `f"{gap:+.3f}"` when `generalization_gap` passes `_is_number`, otherwise
  `n/a`.
- WHEN `kind == "generalization"` THEN the headline SHALL be:
  `gap outlook: {verdict or "unknown"} (gap {gap_txt}, tuned {tuned_score} vs held-out {held_out_score})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_gap_outlook()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_052_gap_outlook.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_gap_outlook.py`.
