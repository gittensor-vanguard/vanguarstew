# Spec 048 — repo task mean summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1138
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) -> *Benchmark integrity*
- **Related:** [`benchmark/repo_task_mean.py`](../../benchmark/repo_task_mean.py),
  [`benchmark/comparability.py`](../../benchmark/comparability.py)

This spec documents the as-built contract of `benchmark/repo_task_mean.py`. It introduces no
behavior change.

## Why

Multi-repo and generalization benchmark artifacts can hide uneven task density. A headline score
may look healthy even when most tasks came from one repository. `summarize_repo_task_mean()` gives
operators a read-only way to inspect average tasks per scored repo.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay artifact is not a dict THEN `summarize_repo_task_mean(artifact)` SHALL treat it
  as `{}` and return an invalid summary, not raise.
- `_dict(value)` SHALL return `value` when it is a dict, otherwise `{}`.

### Whole-number task semantics

- Only built-in `int` values SHALL count as task counts.
- `bool` SHALL NOT be treated as an integer task count.
- `float` values SHALL NOT be treated as integer task counts.
- Only positive task counts SHALL contribute to `scored_repos`, `total_tasks`, and
  `mean_tasks_per_repo`.

### `per_repo` row handling

- WHEN `per_repo` is missing THEN the row set SHALL be empty.
- WHEN `per_repo` is not a list THEN the row set SHALL be empty and a warning SHALL be logged.
- WHEN a row is not a dict THEN that row SHALL be skipped and a warning SHALL be logged.
- WHEN a row lacks a positive integer `tasks` value THEN that row SHALL NOT count as scored.

### Artifact-kind branches

Classification SHALL use `artifact_kind` from `benchmark/comparability.py`.

Every summary SHALL include:

| Key | Always present | Value when unavailable |
| --- | --- | --- |
| `kind` | yes | `artifact_kind` result |
| `scored_repos` | yes | `0` |
| `total_tasks` | yes | `0` |
| `mean_tasks_per_repo` | yes | `None` |
| `partitions` | yes | `None` outside generalization |

1. **`single`** — a positive integer top-level `tasks` value SHALL produce
   `scored_repos == 1`, `total_tasks == tasks`, and `mean_tasks_per_repo == float(tasks)`.
   Missing, zero, negative, bool, or non-integer `tasks` SHALL produce no scored repo.
2. **`multi`** — stats SHALL be computed from positive integer `tasks` values in top-level
   `per_repo` rows. The mean SHALL be `round(total_tasks / scored_repos, 3)` when at least one
   repo is scored, otherwise `None`.
3. **`generalization`** — stats SHALL be computed separately for `tuned.per_repo` and
   `held_out.per_repo` under `partitions`, then combined at the top level by summing
   `scored_repos` and `total_tasks`. The top-level mean SHALL be rounded to three decimals when
   at least one repo is scored, otherwise `None`.
4. **Other/invalid kinds** — SHALL return zero counts, `mean_tasks_per_repo is None`, and
   `partitions is None`.

### Headline

`repo_task_mean_headline(summary)` SHALL return exactly:

`repo task mean: {kind} {scored_repos} scored repo(s), mean {mean_txt} tasks/repo`

- `kind` SHALL default to `unknown` when missing.
- `mean_txt` SHALL be formatted as `{mean:.3f}` only when `mean_tasks_per_repo` is an int or float
  and not a bool.
- Otherwise `mean_txt` SHALL be `n/a`.

### Pure evaluation

- The module SHALL perform no I/O.
- `summarize_repo_task_mean()` SHALL NOT mutate its input artifact.

## Out of scope

- Changing artifact kind classification.
- Changing task-count semantics.
- Adding CLI behavior beyond the existing `scripts/repo_task_mean.py` integration tests.

## Verification

- `tests/test_spec_048_repo_task_mean.py` exercises each EARS block above.
- Existing integration coverage remains in `tests/test_repo_task_mean.py`.
