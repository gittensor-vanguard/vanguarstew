# Spec 058 — repo score spread summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1616
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/composite_spread.py`](../../benchmark/composite_spread.py) (judge-vs-objective delta),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/repo_task_mean.py`](../../benchmark/repo_task_mean.py) (per-repo task means)

This spec makes the **existing, implicit** repo-score-spread contract explicit. It describes the
as-built behavior of `benchmark/repo_score_spread.py`; it introduces **no behavior change**.

## Why

A multi-repo run's headline `composite_mean` hides how evenly the agent scored across repos. This
read-only utility reports `min`/`max`/`range` of per-repo `composite_mean` so a dashboard can flag
a run carried by one repo. A generalization artifact additionally reports per-partition spreads.

## User stories

1. **As a benchmark operator**, I can read how uneven per-repo composite scores are behind the mean.
2. **As a CI maintainer**, I can log a stable `repo_score_spread_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_repo_score_spread(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_int(value)` SHALL be true only for built-in `int` values that are not `bool`.

### Numeric semantics (`_is_number`)

- Only **finite**, non-boolean `int`/`float` values SHALL count as numeric; a `bool`, `str`,
  `None`, `NaN`, or `Infinity` SHALL NOT (no crash, no 1.0/0.0 coercion).

### Per-repo scores (`_repo_scores`)

- WHEN `per_repo` is a `list` THEN each dict entry with a numeric `composite_mean` SHALL contribute
  that score rounded to 3 decimal places; non-dict entries and non-numeric means SHALL be skipped.
- OTHERWISE WHEN the top-level `composite_mean` is numeric THEN `_repo_scores` SHALL return a
  one-element list (that mean rounded to 3 dp); OTHERWISE `[]`.

### Spread helper (`_spread`)

- WHEN `scores` is empty THEN `_spread` SHALL return
  `{"scored_repos": 0, "min": None, "max": None, "range": None}`.
- OTHERWISE it SHALL return `scored_repos`, `min`, `max`, and `range` rounded to 3 dp
  (`max - min`).

### Repo score spread summary (`summarize_repo_score_spread`)

Every summary SHALL include: `kind`, `scored_repos`, `min`, `max`, `range`, `partitions`.

- `kind` SHALL come from `artifact_kind(artifact)`.
- WHEN `kind` is `generalization` THEN the top-level spread SHALL combine tuned and held-out repo
  scores, and `partitions` SHALL be
  `{"tuned": _spread(...), "held_out": _spread(...)}`.
- OTHERWISE the top-level spread SHALL come from `_repo_scores(artifact)` and `partitions` SHALL
  be `None`.

### Repo score spread headline

- WHEN `scored_repos` is missing, not an int, or `0` THEN the headline SHALL be exactly:
  `repo score spread: no scored repos`.
- OTHERWISE WHEN `range` passes `_is_number` THEN `range` SHALL format as `{range:.3f}`, else
  `n/a`, and the headline SHALL be:
  `repo score spread: range {rng_txt} across {count} repo(s) (min {min}, max {max})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_repo_score_spread()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_058_repo_score_spread.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_repo_score_spread.py`.
