# Spec 055 — task independence gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1168
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/task_integrity.py`](../../benchmark/task_integrity.py) (distinct freeze points),
  [`benchmark/task_uniformity.py`](../../benchmark/task_uniformity.py) (equal window lengths),
  [`benchmark/taskgen.py`](../../benchmark/taskgen.py) (task generation)

This spec makes the **existing, implicit** task-independence contract explicit. It describes the
as-built behavior of `benchmark/task_independence.py`; it introduces **no behavior change**.

## Why

`task_integrity` checks distinct freeze points, but distinctness alone does not make replay
windows independent. `check_task_independence` gates whether freeze indices are far enough apart
that revealed windows do not overlap for a given horizon.

## User stories

1. **As a benchmark operator**, I can verify task replay windows are independent before trusting
   aggregate win/loss records.
2. **As a CI maintainer**, I can gate on `check_task_independence()` with a stable headline.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Constants

- The module SHALL expose `DEFAULT_HORIZON = 5` as the default replay horizon.

### Input coercion

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_nonneg_int(value)` SHALL be true only for non-negative built-in `int` values (not `bool`).

### Independence gate (`check_task_independence`)

Every result SHALL include: `passed`, `checks`, `task_count`, `min_gap`, `horizon`.

All checks SHALL be reported; each fails closed; `passed` is true only when every check passes.

1. **`is_task_list`** — `tasks` SHALL be a non-empty list whose every entry is a `dict`.
2. **`freeze_indices_valid`** — every task SHALL carry a non-negative integer `freeze_index`.
3. **`windows_independent`** — WHEN at least two valid indices exist THEN the smallest gap between
   consecutive sorted indices SHALL be `> horizon`; a single task SHALL pass trivially.

`min_gap` SHALL be the smallest consecutive gap when at least two valid indices exist; otherwise
`None`.

### Failed checks (`failed_checks`)

- WHEN `checks` is not a list THEN `failed_checks` SHALL return `[]`.
- OTHERWISE it SHALL return the names of checks whose `passed` field is false.

### Task independence headline

- WHEN `checks` is missing or empty THEN the headline SHALL be exactly:
  `task independence: no checks evaluated`.
- WHEN `passed` is true THEN the headline SHALL be:
  `task independence: INDEPENDENT ({task_count} tasks, all checks passed)`.
- OTHERWISE the headline SHALL list failed check names:
  `task independence: OVERLAPPING ({n}/{total} checks failed: ...)`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_task_independence()` SHALL NOT mutate its input list.

## Verification

- `tests/test_spec_055_task_independence.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_task_independence.py`.
