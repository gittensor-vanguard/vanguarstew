# Spec 057 — task integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1174
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/task_independence.py`](../../benchmark/task_independence.py) (non-overlapping windows),
  [`benchmark/task_uniformity.py`](../../benchmark/task_uniformity.py) (equal window lengths),
  [`benchmark/taskgen.py`](../../benchmark/taskgen.py) (task generation)

This spec makes the **existing, implicit** task-integrity contract explicit. It describes the
as-built behavior of `benchmark/task_integrity.py`; it introduces **no behavior change**.

## Why

Artifact gates (`tally_integrity`, `aggregate_integrity`) verify replay output, but nothing
verifies the *input* task set. Duplicate freeze points bias win/loss records and break M1
re-run stability; empty `revealed` windows have no reference trajectory to judge against.

## User stories

1. **As a benchmark operator**, I can verify a task set is well-formed before running replay.
2. **As a CI maintainer**, I can gate on `check_task_integrity()` with a stable headline.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_nonempty_str(value)` SHALL be true only when `value` is a `str` with non-whitespace
  content after stripping.

### Integrity gate (`check_task_integrity`)

Every result SHALL include: `passed`, `checks`, `task_count`, `distinct_freeze_points`.

All checks SHALL be reported; each fails closed; `passed` is true only when every check passes.

1. **`is_task_list`** — `tasks` SHALL be a non-empty list whose every entry is a `dict`.
2. **`freeze_commits_valid`** — every task SHALL carry a non-empty string `freeze_commit`.
3. **`distinct_freeze_points`** — WHEN freeze commits are valid THEN no two tasks SHALL share a
   `freeze_commit`; WHEN commits are invalid THEN the check SHALL fail with an invalid-commit
   detail.
4. **`revealed_non_empty`** — every task's `revealed` SHALL be a non-empty list.

`distinct_freeze_points` SHALL be the count of distinct valid freeze commits (0 when none).

### Failed checks (`failed_checks`)

- WHEN `checks` is not a list THEN `failed_checks` SHALL return `[]`.
- OTHERWISE it SHALL return the names of checks whose `passed` field is false.

### Task integrity headline

- WHEN `checks` is missing or empty THEN the headline SHALL be exactly:
  `task integrity: no checks evaluated`.
- WHEN `passed` is true THEN the headline SHALL be:
  `task integrity: SOUND ({task_count} tasks, all checks passed)`.
- OTHERWISE the headline SHALL list failed check names:
  `task integrity: DEGENERATE ({n}/{total} checks failed: ...)`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_task_integrity()` SHALL NOT mutate its input list.

## Verification

- `tests/test_spec_057_task_integrity.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_task_integrity.py`.
