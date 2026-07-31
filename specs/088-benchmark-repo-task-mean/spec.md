# Spec 088 — repo task mean summary

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1132
- **Supersedes:** [`specs/049-benchmark-repo-task-mean`](../049-benchmark-repo-task-mean/spec.md) (#1145),
  [`specs/090-benchmark-repo-task-mean`](../090-benchmark-repo-task-mean/spec.md) (#1138) — see
  [Canonical spec](#canonical-spec)
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/comparability.py`](../../benchmark/comparability.py) (artifact kind classification),
  [`benchmark/scored_fraction.py`](../../benchmark/scored_fraction.py) (repo-coverage counterpart)

This spec makes the **existing, implicit** repo-task-mean contract explicit. It describes the
as-built behavior of `benchmark/repo_task_mean.py`; it introduces **no behavior change**. A
multi-repo headline can hide whether breadth came from many tasks everywhere or one heavy repo —
that task-density signal must be written down and verified.

## Canonical spec

`benchmark/repo_task_mean.py` was specified three times — this document (#1132), spec 090 (#1138)
and spec 049 (#1145) — by three contributors who each read the module as unspecified. The three
agree on the module's behavior, so nothing was in conflict, but nothing marked which one a change
is reviewed against either (#2143). **This document is the canonical spec for the module.** The
other two are marked superseded and point here; they are kept because their contract tests still
run against the criteria they state.

This one is canonical because it states the module's contract most completely without contradicting
it. Every criterion in spec 049 appears here; this is the only one of the three that pins the order
`_rows_from_per_repo` returns surviving rows in, the coercion of a non-`dict` summary passed to the
headline, and the never-raises guarantee; and it is the only one whose headline clause does not
contradict `repo_task_mean_headline`, which formats the mean only for a *finite* non-boolean number
— specs 049 and 090 both say "an int or float and not a bool", which would render a `nan` mean as
`nan` where the module renders `n/a`.

## Why

A multi-repo run can score every repo but with very different task counts per repo.
`summarize_repo_task_mean()` reports the average tasks per *scored* repo (a repo contributes only
when it has a positive whole-number `tasks` count), the reproducible read-only summary for CI
dashboards. Making its contract explicit lets reviewers check task-density changes against intent.

## User stories

1. **As a benchmark operator**, I can read `total_tasks / scored_repos` before trusting that a
   multi-repo headline reflects broad task coverage.
2. **As a CI maintainer**, I can log a stable `repo_task_mean_headline()` string alongside the JSON
   summary.
3. **As a reviewer**, malformed `per_repo` handling, the generalization partition split, and the
   headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- WHEN the replay `artifact` is not a `dict` THEN `summarize_repo_task_mean(artifact)` SHALL treat
  it as `{}` and evaluate (not raise).
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Whole-number count semantics (`_is_int`)

- Only built-in `int` values SHALL count as whole-number task counts.
- `bool` SHALL NOT be treated as an integer (avoids truthy counts).
- `float` values — including whole-number floats such as `5.0` — SHALL NOT be treated as integers.

### `per_repo` row extraction (`_rows_from_per_repo`)

- WHEN `per_repo` is `None` THEN `_rows_from_per_repo` SHALL return `[]` silently.
- WHEN `per_repo` is a truthy non-list THEN it SHALL log a warning and return `[]` (never
  iterate/coerce it).
- A non-dict entry inside the list SHALL be skipped with a warning; the surviving dict rows SHALL be
  returned in order.

### Partition stats (`_partition_stats`)

- A repo row SHALL count toward the mean only when its `tasks` value passes `_is_int` AND is `> 0`
  (a zero, negative, missing, or non-integer `tasks` contributes nothing).
- `scored_repos` SHALL be the number of counted rows and `total_tasks` their sum.
- WHEN `scored_repos > 0` THEN `mean_tasks_per_repo` SHALL be `round(total_tasks / scored_repos, 3)`;
  WHEN `scored_repos == 0` THEN it SHALL be `None`.

### Artifact-kind branches (`summarize_repo_task_mean`)

- Every returned summary SHALL include the keys `kind`, `scored_repos`, `total_tasks`,
  `mean_tasks_per_repo`, and `partitions`.
- WHEN `kind` is `single` AND the top-level `tasks` is a positive `int` THEN the summary SHALL be
  `scored_repos == 1`, `total_tasks == tasks`, `mean_tasks_per_repo == float(tasks)`, and
  `partitions` `None`; otherwise a single artifact SHALL report zero counts with a `None` mean.
- WHEN `kind` is `multi` THEN the summary SHALL be the `_partition_stats` of the top-level
  `per_repo`, with `partitions` `None`.
- WHEN `kind` is `generalization` THEN the summary SHALL carry a `partitions` mapping with a `tuned`
  and a `held_out` `_partition_stats`, and the overall `scored_repos`/`total_tasks` summed across
  the two partitions (`mean_tasks_per_repo` `None` when the summed `scored_repos` is 0).
- WHEN `kind` is `invalid` THEN the summary SHALL report zero counts, a `None` mean, and `partitions`
  `None`.

### Repo task mean headline (`repo_task_mean_headline`)

- The headline SHALL be `"repo task mean: {kind} {scored_repos} scored repo(s), mean {mean} tasks/repo"`,
  where `{mean}` is `mean_tasks_per_repo` formatted to three decimals when it is a real (non-bool)
  number, else `"n/a"`.
- WHEN the summary is not a `dict` THEN it SHALL be coerced to `{}` (kind `"unknown"`, mean `"n/a"`).

### Pure evaluation

- `summarize_repo_task_mean` SHALL NOT mutate its input artifact.
- The module SHALL perform no I/O and SHALL never raise on malformed input (malformed rows are
  logged and skipped).

## Verification

- `tests/test_spec_088_repo_task_mean.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_repo_task_mean.py`.
- The superseded specs ([049](../049-benchmark-repo-task-mean/spec.md),
  [090](../090-benchmark-repo-task-mean/spec.md)) keep the contract tests each names, which still
  run; they assert the same as-built behavior from a narrower angle and are left in place.
