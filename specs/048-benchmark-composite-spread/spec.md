# Spec 048 — composite spread summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1141
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/leaderboard.py`](../../benchmark/leaderboard.py) (per-row component means),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/margin_outlook.py`](../../benchmark/margin_outlook.py) (headline margin telemetry)

This spec makes the **existing, implicit** composite-spread contract explicit. It describes the
as-built behavior of `benchmark/composite_spread.py`; it introduces **no behavior change**.

## Why

`leaderboard` shows component means per row, but nothing exposes the gap between judge and
objective means as a single number for trending. `summarize_composite_spread` reports
`judge_mean - objective_mean` from the headline partition's `composite_parts`.

## User stories

1. **As a benchmark operator**, I can read the judge-vs-objective spread behind a headline score.
2. **As a CI maintainer**, I can log a stable `composite_spread_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_composite_spread(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Numeric semantics (`_is_number`, `_round3`)

- Only **finite**, non-boolean `int`/`float` values SHALL count as numeric; a `NaN`/`Infinity`
  mean (which `json` round-trips verbatim) SHALL NOT, so it degrades to `None`/`n/a` rather than
  poisoning the reported `spread` (mirrors `component_mix` and `trend`).
- `_round3(value)` SHALL return `round(float(value), 3)` when `value` passes `_is_number`,
  otherwise `None`.

### Headline partition (`_headline_partition`)

- WHEN both `tuned` and `held_out` are `dict` values THEN `_headline_partition` SHALL return
  `tuned`.
- OTHERWISE it SHALL return the top-level artifact dict.

### Composite parts (`_headline_parts`)

- SHALL read `judge_mean` and `objective_mean` from `composite_parts` when that value is a `dict`.
- WHEN `composite_parts` is missing or not a `dict` THEN both means SHALL be `None` (with a warning
  when non-`None` and non-dict).
- WHEN the headline partition carries a numeric `scored_repos` of `0` THEN **both** means SHALL be
  `None` (and therefore `spread` too): the run scored no repos, so its `composite_parts` are
  `_mean([])` placeholders of `0.0` rather than real component scores, and reporting them
  publishes a fabricated `judge 0.0 vs objective 0.0 (delta +0.000)` for a run that measured
  nothing.
- WHEN the artifact carries **no** `scored_repos` key THEN the means SHALL be read normally — a
  genuine single-repo run keeps its real values, including a legitimate `0.0`.

### Composite spread summary (`summarize_composite_spread`)

Every summary SHALL include: `kind`, `judge_mean`, `objective_mean`, `spread`.

- `kind` SHALL come from `artifact_kind(artifact)`.
- WHEN both means pass `_is_number` THEN `spread` SHALL be `round(judge_mean - objective_mean, 3)`.
- OTHERWISE `spread` SHALL be `None`.

### Composite spread headline

- WHEN `spread` passes `_is_number` THEN `spread_txt` SHALL be `f"{spread:+.3f}"`, otherwise `n/a`.
- The headline SHALL be:
  `composite spread: judge {judge_mean} vs objective {objective_mean} (delta {spread_txt})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_composite_spread()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_048_composite_spread.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_composite_spread.py`.
