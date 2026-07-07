# Spec 046 — repo task mean summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1132
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/partition_task_share.py`](../../benchmark/partition_task_share.py) (partition task counts)

This spec makes the **existing, implicit** repo-task-mean contract explicit. It describes the
as-built behavior of `benchmark/repo_task_mean.py`; it introduces **no behavior change**.

## Why

`partition_task_share` reports how tasks split across generalization partitions;
`summarize_repo_task_mean()` reports how many tasks each scored repo contributed on average.
Making its contract explicit lets reviewers check task-density changes against intent.

## User stories

1. **As a benchmark operator**, I can read mean tasks per repo before trusting a headline composite.
2. **As a CI maintainer**, I can log a stable `repo_task_mean_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling, logging, and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_repo_task_mean(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number task counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Per-repo row parsing (`_rows_from_per_repo`)

- WHEN `per_repo` is `None` THEN `_rows_from_per_repo` SHALL return `[]` (no warning).
- WHEN `per_repo` is not a `list` THEN `_rows_from_per_repo` SHALL log a warning and return `[]`.
- WHEN a `per_repo` list entry is not a `dict` THEN `_rows_from_per_repo` SHALL log a warning,
  skip that entry, and continue.
- WHEN a `per_repo` row is a `dict` THEN it SHALL be included in the parsed row list.

### Partition stats (`_partition_stats`)

- `_partition_stats` SHALL count only rows whose `tasks` passes `_is_int` AND `tasks > 0`.
- `scored_repos` SHALL be the count of such rows; `total_tasks` SHALL be their sum.
- WHEN `scored_repos > 0` THEN `mean_tasks_per_repo` SHALL be `round(total_tasks / scored_repos, 3)`.
- WHEN `scored_repos == 0` THEN `mean_tasks_per_repo` SHALL be `None`.

### Artifact-kind branches (`summarize_repo_task_mean`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL include: `kind`, `scored_repos`, `total_tasks`, `mean_tasks_per_repo`,
`partitions`.

1. **`single`** — WHEN top-level `tasks` passes `_is_int` and is `> 0` THEN
   `scored_repos` SHALL be `1`, `total_tasks` SHALL echo `tasks`, and `mean_tasks_per_repo` SHALL
   be `float(tasks)`; otherwise all three SHALL be `0`/`0`/`None`; `partitions` SHALL be `None`.
2. **`multi`** — top-level stats from `_partition_stats(artifact["per_repo"])`; `partitions`
   SHALL be `None`.
3. **`generalization`** — per-partition stats under `partitions["tuned"]` and
   `partitions["held_out"]`; overall `scored_repos` and `total_tasks` SHALL be the sums of both
   partition stats; overall `mean_tasks_per_repo` SHALL be
   `round(total_tasks / scored_repos, 3)` when `scored_repos > 0`, otherwise `None`.
4. **`invalid`** — `scored_repos` and `total_tasks` SHALL be `0`, `mean_tasks_per_repo` SHALL be
   `None`, and `partitions` SHALL be `None`.

### Repo task mean headline

- `kind` in the headline SHALL be the summary's `kind` field, or `unknown` when missing/falsy.
- `mean_txt` SHALL be `f"{mean:.3f}"` when `mean` is a non-boolean `int` or `float` (including
  non-finite values such as `NaN`/`inf` — the as-built formatter does not filter them), otherwise
  `n/a`.
- `scored_repos` SHALL be interpolated directly into the headline (missing values appear as
  `None` in the formatted string).
- The headline SHALL be exactly:
  `repo task mean: {kind} {scored_repos} scored repo(s), mean {mean_txt} tasks/repo`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_repo_task_mean()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_046_repo_task_mean.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_repo_task_mean.py`.
