# Spec 041 — partition task share summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1095
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/repo_task_mean.py`](../../benchmark/repo_task_mean.py) (average tasks per repo)

This spec makes the **existing, implicit** partition-task-share contract explicit. It describes the
as-built behavior of `benchmark/partition_task_share.py`; it introduces **no behavior change**.
A generalization run whose headline composite looks balanced can still hide uneven task sampling
between `tuned` and `held_out` — that distribution must be written down and verified.

## Why

`repo_task_mean` reports average tasks per repo; `summarize_partition_task_share()` reports what
fraction of all scored tasks came from each partition. Making its contract explicit lets reviewers
check partition-task-share changes against intent.

## User stories

1. **As a benchmark operator**, I can read tuned vs held-out task shares for generalization
   dashboards.
2. **As a CI maintainer**, I can log a stable `partition_task_share_headline()` string alongside
   the JSON summary.
3. **As a reviewer**, malformed-input handling, extra dict keys, logging, and every headline
   branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_partition_task_share(artifact)` SHALL
  treat it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- Extra keys on the input `artifact` dict (fields other than those read for classification and
  task counting) SHALL be ignored and SHALL NOT affect summary evaluation.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number task counts.
- `bool` SHALL NOT be treated as an integer.
- `float` values — including whole-number floats such as `4.0` — SHALL NOT be treated as integers.
- NumPy integer scalars (e.g. `numpy.int64`) SHALL NOT be treated as integers (only built-in
  `int` passes `_is_int`).

### Finite numeric semantics (`_is_number`)

- Only finite, non-boolean `int`/`float` values SHALL count as numeric for headline share
  formatting.
- `bool`, `NaN`, `inf`, and non-numeric types SHALL NOT be treated as numeric.

### Per-repo row parsing (`_rows_from_per_repo`)

- WHEN `per_repo` is `None` THEN `_rows_from_per_repo` SHALL return `[]` (no warning).
- WHEN `per_repo` is not a `list` THEN `_rows_from_per_repo` SHALL log a warning and return `[]`.
- WHEN a `per_repo` list entry is not a `dict` THEN `_rows_from_per_repo` SHALL log a warning,
  skip that entry, and continue.
- WHEN a `per_repo` row is a `dict` THEN it SHALL be included in the parsed row list.

### Scored-task counting (`_scored_tasks`)

- `_scored_tasks` SHALL sum `tasks` from parsed `per_repo` rows only when `tasks` passes `_is_int`
  AND `tasks > 0`.
- WHEN `tasks` is missing, zero, negative, non-integer, or boolean THEN that row SHALL contribute
  `0` to the sum (not raise).

### Partition share (`_partition_share` / `_partition_entry`)

- WHEN `tasks` or `total` fails `_is_int` OR `total <= 0` THEN `_partition_share` SHALL return
  `None` (distinct from `0.0` when `total > 0` and `tasks == 0`).
- WHEN `tasks` and `total` are valid `_is_int` values and `total > 0` THEN `_partition_share`
  SHALL return `round(tasks / total, 3)`.
- `_partition_entry(tasks, total)` SHALL return `{"tasks": tasks, "share": _partition_share(tasks, total)}`.

### Artifact-kind branches (`summarize_partition_task_share`)

Classification SHALL use `artifact_kind` from `benchmark/comparability`.

Every summary SHALL include: `kind`, `total_tasks`, `partitions`.

1. **`single`** — `total_tasks` SHALL be the top-level `tasks` value when it passes `_is_int` and
   is `> 0`, otherwise `0`; `partitions` SHALL be `None`.
2. **`multi`** — `total_tasks` SHALL be `_scored_tasks(artifact["per_repo"])`; WHEN
   `total_tasks > 0` THEN `partitions` SHALL be `{"multi": _partition_entry(total_tasks, total_tasks)}`
   (share `1.0`); WHEN `total_tasks == 0` THEN `partitions` SHALL be `None`.
3. **`generalization`** — for each of `tuned` and `held_out`, task counts SHALL come from
   `_scored_tasks` on that partition's `per_repo`; `total_tasks` SHALL be the sum of both partition
   counts; `partitions` SHALL map each partition name to `_partition_entry(tasks, total_tasks)`.
4. **`invalid`** — `total_tasks` SHALL be `0` and `partitions` SHALL be `None`.

### Partition task share headline

- WHEN `total_tasks` is missing, not a positive `_is_int`, or `<= 0` THEN the headline SHALL be
  exactly: `partition task share: no scored tasks`.
- WHEN `kind == "generalization"` and `total_tasks > 0` THEN the headline SHALL be exactly:
  `partition task share: {total} task(s) (tuned {tuned_share}, held-out {held_share})` where each
  share uses percent formatting when the partition `share` passes `_is_number`, otherwise `n/a`.
- WHEN `kind` is not `generalization` and `total_tasks > 0` THEN the headline SHALL be exactly:
  `partition task share: {kind} {total} scored task(s)` (using the summary's `kind` field, or
  `unknown` when missing).

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_partition_task_share()` SHALL NOT mutate its input dict.

## Verification

- `tests/test_spec_041_partition_task_share.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_partition_task_share.py`.
