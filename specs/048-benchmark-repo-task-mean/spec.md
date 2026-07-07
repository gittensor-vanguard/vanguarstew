# Spec 048 — repo task mean summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1138
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/partition_task_share.py`](../../benchmark/partition_task_share.py) (partition task shares),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification)

This spec makes the **existing, implicit** repo-task-mean contract explicit. It describes the
as-built behavior of `benchmark/repo_task_mean.py`; it introduces **no behavior change**.

## Why

A headline composite does not show whether breadth came from many tasks everywhere or one heavy
repo. `summarize_repo_task_mean()` reports average tasks per scored repo so dashboards can spot
uneven sampling density.

## User stories

1. **As a benchmark operator**, I can read mean tasks per scored repo from a replay artifact.
2. **As a CI maintainer**, I can log a stable `repo_task_mean_headline()` string alongside the
   JSON summary.
3. **As a reviewer**, malformed-input handling and every summary branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_repo_task_mean(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number task counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### `per_repo` row parsing (`_rows_from_per_repo`)

- WHEN `per_repo` is `None` THEN `_rows_from_per_repo` SHALL return `[]`.
- WHEN `per_repo` is not a `list` THEN it SHALL log a warning and return `[]`.
- Non-dict entries SHALL be logged and skipped; dict entries SHALL be retained in order.

### Partition stats (`_partition_stats`)

- SHALL count only rows whose `tasks` is a positive `_is_int`.
- `scored_repos` SHALL be the count of such rows; `total_tasks` SHALL be their sum.
- WHEN `scored_repos > 0` THEN `mean_tasks_per_repo` SHALL be `round(total_tasks / scored_repos, 3)`.
- WHEN `scored_repos == 0` THEN `mean_tasks_per_repo` SHALL be `None`.

### Artifact-kind branches (`summarize_repo_task_mean`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL include: `kind`, `scored_repos`, `total_tasks`, `mean_tasks_per_repo`,
`partitions`.

1. **`single`** — WHEN top-level `tasks` is a positive `_is_int` THEN `scored_repos` SHALL be `1`,
   `total_tasks` SHALL equal `tasks`, and `mean_tasks_per_repo` SHALL be `float(tasks)`; otherwise
   all three count/mean fields SHALL be `0`/`0`/`None`. `partitions` SHALL be `None`.
2. **`multi`** — stats from `_partition_stats(artifact["per_repo"])`; `partitions` SHALL be `None`.
3. **`generalization`** — per-partition stats under `partitions["tuned"]` and
   `partitions["held_out"]`; overall `scored_repos`/`total_tasks`/`mean_tasks_per_repo` summed
   across partitions (mean from total tasks divided by total scored repos when `scored > 0`).
4. **`invalid`** — all count/mean fields zero or `None` as above; `partitions` `None`.

### Repo task mean headline

- Non-dict summaries SHALL be coerced via `_dict`.
- `kind` SHALL default to `"unknown"` when missing.
- Mean text SHALL be `f"{mean:.3f}"` when `mean` is a non-boolean `int`/`float`, otherwise `n/a`.
- The headline SHALL be:
  `repo task mean: {kind} {scored} scored repo(s), mean {mean_txt} tasks/repo`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_repo_task_mean()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_048_repo_task_mean.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_repo_task_mean.py`.
