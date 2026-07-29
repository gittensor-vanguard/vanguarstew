# Spec 047 — partition task share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1133
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/repo_task_mean.py`](../../benchmark/repo_task_mean.py) (average tasks per repo),
  [`benchmark/scored_fraction.py`](../../benchmark/scored_fraction.py) (scored-repo coverage)

This spec makes the **existing, implicit** partition-task-share contract explicit. It describes
the as-built behavior of `benchmark/partition_task_share.py`; it introduces **no behavior change**.

## Why

`repo_task_mean` reports average tasks per repo; `partition_task_share` reports what fraction of
all scored tasks came from each `tuned` / `held_out` partition — useful when a headline composite
hides uneven sampling between partitions.

## User stories

1. **As a benchmark operator**, I can read how scored tasks are distributed across partitions.
2. **As a CI maintainer**, I can log a stable `partition_task_share_headline()` string alongside
   the JSON summary.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_partition_task_share(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values SHALL NOT be treated as integers.

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Per-repo row parsing (`_rows_from_per_repo`)

- WHEN `per_repo` is `None` THEN `_rows_from_per_repo` SHALL return `[]`.
- WHEN `per_repo` is not a `list` THEN it SHALL log a warning and return `[]`.
- Non-`dict` list entries SHALL be logged and skipped; only `dict` rows SHALL be retained.

### Scored task counting (`_scored_tasks`)

- SHALL sum `row["tasks"]` for each row where `tasks` is a positive `_is_int`.
- Rows with missing, zero, negative, or non-integer `tasks` SHALL be skipped.

### Partition share (`_partition_share`, `_partition_entry`)

- WHEN both `tasks` and `total` pass `_is_int` AND `total > 0` THEN `_partition_share` SHALL
  return `round(tasks / total, 3)`.
- OTHERWISE `_partition_share` SHALL return `None`.
- `_partition_entry` SHALL return `{"tasks": tasks, "share": _partition_share(tasks, total)}`.

### Artifact-kind branches (`summarize_partition_task_share`)

Every summary SHALL include: `kind`, `total_tasks`, `partitions`.

1. **`single`** — `total_tasks` SHALL be `artifact["tasks"]` when that value is a positive
   `_is_int`, otherwise `0`; `partitions` SHALL be `None`.
2. **`multi`** — `total_tasks` SHALL be `_scored_tasks(per_repo)`; WHEN `total_tasks > 0` THEN
   `partitions` SHALL be `{"multi": _partition_entry(total_tasks, total_tasks)}`; OTHERWISE
   `partitions` SHALL be `None`.
3. **`generalization`** — SHALL score `tuned.per_repo` and `held_out.per_repo` separately;
   `total_tasks` SHALL be their sum; `partitions` SHALL include both partition entries computed
   against the combined total.
4. **`invalid`** — `total_tasks` SHALL be `0`, `partitions` SHALL be `None`.

### Partition task share headline

- `_fmt_share(value)` SHALL format as `f"{float(value):.1%}"` when `value` passes `_is_number`,
  otherwise `n/a`.
- WHEN `total_tasks` is missing, not a non-negative `_is_int`, or `0` THEN the headline SHALL be
  exactly: `partition task share: no scored tasks`.
- WHEN `kind == "generalization"` and `total_tasks > 0` THEN the headline SHALL include tuned and
  held-out partition shares.
- WHEN `total_tasks > 0` for other kinds THEN the headline SHALL be:
  `partition task share: {kind} {total_tasks} scored task(s)`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_partition_task_share()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_047_partition_task_share.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_partition_task_share.py`.
