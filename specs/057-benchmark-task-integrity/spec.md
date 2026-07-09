# Spec 057 — task integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1174
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/task_integrity.py`](../../benchmark/task_integrity.py) (this gate),
  [`benchmark/task_uniformity.py`](../../benchmark/task_uniformity.py) (equal window lengths),
  [`benchmark/task_independence.py`](../../benchmark/task_independence.py) (non-overlapping windows),
  [`specs/056-benchmark-task-uniformity/spec.md`](../056-benchmark-task-uniformity/spec.md)

This spec makes the **existing, implicit** task-integrity contract explicit. It describes the
as-built behavior of `benchmark/task_integrity.py`; it introduces **no behavior change**.

## Why

`taskgen.generate_tasks` selects freeze points from a repo's history, and `run_replay` scores the
agent at each freeze point against that task's `revealed` window. The artifact-level integrity
gates (`tally_integrity`, `aggregate_integrity`) verify the run *output*; nothing verifies the
*input* task set. A duplicate freeze point scores one scenario twice — biasing the win/loss record
and breaking the M1 "re-runs are stable" guarantee — and an empty `revealed` window has no
reference trajectory to judge against. This gate fails **closed**: any condition it cannot
positively confirm is a failure, never a pass, and malformed input is reported rather than raised.

## User stories

1. **As a benchmark operator**, I can verify a task set is well-formed before spending a replay on it.
2. **As a CI maintainer**, I can gate on `check_task_integrity()` with a stable one-line headline.
3. **As a reviewer**, empty-list, missing-key, and duplicate-freeze-point behavior is written down.

## Acceptance criteria (EARS)

### Input coercion

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_nonempty_str(value)` SHALL return `True` only when `value` is a `str` with non-whitespace
  content; otherwise `False` (including for `None`, blanks, and non-string types).

### Integrity gate (`check_task_integrity`)

Every result SHALL include: `passed`, `checks`, `task_count`, `distinct_freeze_points`.

- `task_count` SHALL be the number of entries that are `dict` objects.
- All checks SHALL always be reported; each fails closed; `passed` is true only when every check
  passes.

The four checks, reported in order, are:

1. **`is_task_list`** — `tasks` SHALL be a non-empty list whose every entry is a `dict`.
   WHEN `tasks` is empty, is not a list, or contains any non-`dict` entry THEN the check SHALL fail.
2. **`freeze_commits_valid`** — every task SHALL carry a non-empty string `freeze_commit`.
   WHEN any task's `freeze_commit` is missing, blank/whitespace, or not a string THEN the check
   SHALL fail. It also fails whenever `is_task_list` fails.
3. **`distinct_freeze_points`** — no two tasks SHALL share a `freeze_commit`.
   WHEN every `freeze_commit` is valid THEN the check SHALL pass only when the count of distinct
   `freeze_commit` values equals the number of tasks; WHEN a duplicate exists THEN the check SHALL
   fail with a duplicate-count detail; WHEN any `freeze_commit` is invalid THEN the check SHALL
   fail with a "cannot check distinctness" detail rather than a duplicate count.
4. **`revealed_non_empty`** — every task's `revealed` SHALL be a non-empty `list`.
   WHEN any task's `revealed` is missing, empty, or not a list THEN the check SHALL fail.

The `distinct_freeze_points` **result field** SHALL be the number of distinct **valid**
`freeze_commit` values observed among the `dict` tasks — `0` for a malformed or non-list task set.
It is a reported diagnostic and is distinct from the `distinct_freeze_points` **check** above.

### Fail-closed edge cases

- WHEN `tasks` is `None`, a string, an int, a dict, or any non-list THEN every check SHALL fail,
  `task_count` SHALL be `0`, `distinct_freeze_points` SHALL be `0`, and no exception SHALL be raised.
- WHEN `tasks` is `[]` THEN `is_task_list` SHALL fail and `task_count` SHALL be `0`.
- WHEN a task is missing a required key (`freeze_commit` or `revealed`) THEN the corresponding
  check SHALL fail closed rather than raising `KeyError`.

### Failed checks (`failed_checks`)

- WHEN `result` is not a dict, or its `checks` is not a list THEN `failed_checks` SHALL return `[]`.
- OTHERWISE it SHALL return the `name` of every check whose `passed` field is false.

### Task integrity headline

- WHEN `checks` is missing or empty THEN the headline SHALL be exactly:
  `task integrity: no checks evaluated`.
- WHEN `passed` is true THEN the headline SHALL be:
  `task integrity: SOUND ({task_count} tasks, all checks passed)`.
- OTHERWISE it SHALL list the failed check names:
  `task integrity: DEGENERATE ({n}/{total} checks failed: ...)`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_task_integrity()` SHALL NOT mutate its input list or any task within it.

## Verification

- `tests/test_spec_057_task_integrity.py` exercises each EARS block above.
- Broader coverage (including the CLI) remains in `tests/test_task_integrity.py`.
