# Spec 056 — task uniformity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1171
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/task_integrity.py`](../../benchmark/task_integrity.py) (non-empty revealed windows),
  [`benchmark/task_independence.py`](../../benchmark/task_independence.py) (non-overlapping windows),
  [`specs/055-benchmark-task-independence/spec.md`](../055-benchmark-task-independence/spec.md)

This spec makes the **existing, implicit** task-uniformity contract explicit. It describes the
as-built behavior of `benchmark/task_uniformity.py`; it introduces **no behavior change**.

## Why

`task_integrity` checks each `revealed` window is a non-empty list; `task_independence` checks
windows do not overlap. Neither checks that every window has the **same length** — this gate does.

## User stories

1. **As a benchmark operator**, I can verify every task uses an equally weighted revealed window.
2. **As a CI maintainer**, I can gate on `check_task_uniformity()` with a stable headline.
3. **As a reviewer**, malformed-input handling and every headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_window_len(task)` SHALL return `len(revealed)` when `revealed` is a non-empty list;
  otherwise `None`.

### Uniformity gate (`check_task_uniformity`)

Every result SHALL include: `passed`, `checks`, `task_count`, `window_length`, `distinct_lengths`.

All checks SHALL be reported; each fails closed; `passed` is true only when every check passes.

1. **`is_task_list`** — `tasks` SHALL be a non-empty list whose every entry is a `dict`.
2. **`revealed_windows_present`** — every task SHALL have a non-empty list `revealed` window.
3. **`uniform_window_length`** — WHEN all windows are present THEN every window SHALL have the
   same length; WHEN any window is missing THEN the check SHALL fail with a missing-window detail.

`window_length` SHALL be the common length when uniform; otherwise `None`.
`distinct_lengths` SHALL be the sorted distinct window lengths observed (empty when none).

### Failed checks (`failed_checks`)

- WHEN `checks` is not a list THEN `failed_checks` SHALL return `[]`.
- OTHERWISE it SHALL return the names of checks whose `passed` field is false.

### Task uniformity headline

- WHEN `checks` is missing or empty THEN the headline SHALL be exactly:
  `task uniformity: no checks evaluated`.
- WHEN `passed` is true THEN the headline SHALL be:
  `task uniformity: UNIFORM ({task_count} tasks, window length {window_length})`.
- OTHERWISE the headline SHALL list failed check names:
  `task uniformity: UNEVEN ({n}/{total} checks failed: ...)`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_task_uniformity()` SHALL NOT mutate its input list.

## Verification

- `tests/test_spec_056_task_uniformity.py` exercises each EARS block above.
- Broader coverage remains in `tests/test_task_uniformity.py`.
