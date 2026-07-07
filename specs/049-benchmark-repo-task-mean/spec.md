# Spec 049 — repo task mean summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1145
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/partition_task_share.py`](../../benchmark/partition_task_share.py) (partition task distribution),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/scored_fraction.py`](../../benchmark/scored_fraction.py) (scored-repo coverage)

This spec makes the **existing, implicit** repo-task-mean contract explicit. It describes the
as-built behavior of `benchmark/repo_task_mean.py`; it introduces **no behavior change**.

## Why

Multi-repo runs can score every repo but with very different task counts per repo. A headline
composite alone does not show whether breadth came from many tasks everywhere or one heavy repo.
`summarize_repo_task_mean` reports how many tasks each scored repo contributed on average.

## User stories

1. **As a benchmark operator**, I can read average tasks per scored repo before trusting breadth.
2. **As a CI maintainer**, I can log a stable `repo_task_mean_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_repo_task_mean(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Per-repo row parsing (`_rows_from_per_repo`)

- WHEN `per_repo` is `None` THEN `_rows_from_per_repo` SHALL return `[]`.
- WHEN `per_repo` is not a `list` THEN it SHALL log a warning and return `[]`.
- Non-`dict` list entries SHALL be logged and skipped; only `dict` rows SHALL be retained.

### Partition stats (`_partition_stats`)

- SHALL count repos whose `tasks` field is a positive `_is_int` and sum their task counts.
- `scored_repos` SHALL be the number of such repos; `total_tasks` SHALL be their sum.
- WHEN `scored_repos > 0` THEN `mean_tasks_per_repo` SHALL be `round(total_tasks / scored_repos, 3)`.
- WHEN `scored_repos == 0` THEN `mean_tasks_per_repo` SHALL be `None`.

### Artifact-kind branches (`summarize_repo_task_mean`)

Every summary SHALL include: `kind`, `scored_repos`, `total_tasks`, `mean_tasks_per_repo`,
`partitions`.

1. **`single`** — WHEN `tasks` is a positive `_is_int` THEN `scored_repos` SHALL be `1`,
   `total_tasks` SHALL be `tasks`, and `mean_tasks_per_repo` SHALL be `float(tasks)`; OTHERWISE
   counts SHALL be `0` and `mean_tasks_per_repo` SHALL be `None`; `partitions` SHALL be `None`.
2. **`multi`** — stats from top-level `per_repo`; `partitions` SHALL be `None`.
3. **`generalization`** — per-partition stats for `tuned` and `held_out`, plus overall totals and
   mean summed across both partitions; `partitions` SHALL include both entries.
4. **`invalid`** — all count fields `0`, `mean_tasks_per_repo` `None`, `partitions` `None`.

### Repo task mean headline

- `mean_txt` SHALL be `f"{mean:.3f}"` when `mean` is a non-boolean `int`/`float`, otherwise `n/a`.
- The headline SHALL be:
  `repo task mean: {kind} {scored_repos} scored repo(s), mean {mean_txt} tasks/repo`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_repo_task_mean()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_049_repo_task_mean.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_repo_task_mean.py`.
