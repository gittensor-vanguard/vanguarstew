# Spec 015 — acceptance gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #764
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/runner.py`](../../benchmark/runner.py) (`run_generalization_report` artifacts),
  [`scripts/acceptance.py`](../../scripts/acceptance.py) (CLI gate),
  [`ROADMAP.md`](../../ROADMAP.md) (M3/M4 acceptance run)

This spec makes the **existing, implicit** acceptance-gate contract explicit. It describes the
as-built behavior of `benchmark/acceptance.py`; it introduces **no behavior change**.

## Why

The M3/M4 acceptance run must *complete clean* with a *reasonable* `generalization_gap`.
`check_acceptance` turns that sign-off from manual JSON eyeballing into a reproducible pass/fail
verdict that `scripts/acceptance.py` can gate in CI, so its exact criteria belong on the record.

## User stories

1. **As a benchmark operator**, I can gate a `--generalization` artifact on named acceptance criteria.
2. **As a CI maintainer**, I can fail a pipeline when a partition errored or the gap is out of bound.
3. **As a reviewer**, malformed-input handling and every check/headline branch are written down.

## Acceptance criteria (EARS)

### Input coercion

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_number(value)` SHALL be true only for an `int`/`float` that is not a `bool`.

### Partition errors (`_partition_error`)

- WHEN the partition is not a `dict` THEN it SHALL return `None`.
- WHEN the partition's top-level `error` is truthy THEN it SHALL be returned first.
- OTHERWISE the first `per_repo` row that is a `dict` with a truthy `error`, or a `str` with
  non-whitespace content (a malformed row, treated as an error so a broken artifact fails
  closed), SHALL be returned in row order.
- Non-dict, non-string rows and a non-list `per_repo` SHALL be ignored; a clean partition
  SHALL yield `None`.

### Acceptance gate (`check_acceptance`)

Every result SHALL include: `passed`, `checks`, `generalization_gap`, `max_gap`,
`min_scored_repos`. Defaults: `max_gap = 0.15`, `min_scored_repos = 1`.

All five checks SHALL always be reported, in order, each as
`{"name", "passed", "detail"}`; `passed` is true only when every check passes.

1. **`is_generalization`** — the report SHALL have `dict` values for `tuned` and `held_out`
   and carry a `generalization_gap` key.
2. **`no_partition_error`** — neither partition SHALL carry an error (per `_partition_error`);
   the failure detail SHALL name both partitions' error values.
3. **`both_partitions_scored`** — each partition's `scored_repos` SHALL be a number at or above
   `min_scored_repos`.
4. **`gap_computed`** — `generalization_gap` SHALL be a number (`bool` does not qualify).
5. **`gap_within_bound`** — WHEN the gap is computed THEN it SHALL be at or below `max_gap`
   (the boundary is inclusive); WHEN it is not computed THEN the detail SHALL be `gap not computed`.

The result's `generalization_gap` SHALL be the report's value when it is a number, otherwise
`None`. A non-dict report SHALL simply fail the relevant checks rather than raising.

### Failed checks (`failed_checks`)

- WHEN the result or its `checks` is malformed (non-dict result, non-list `checks`, rows that are
  not dicts, rows missing `name`/`passed`, a non-`str` name, or a `passed` that is not exactly a
  built-in `bool`) THEN the unusable container/rows SHALL be skipped after logging a warning,
  never raising.
- OTHERWISE it SHALL return the names of checks whose `passed` field is false.

### Acceptance headline

- WHEN `checks` is missing, empty, a non-list container, or contains only unusable rows THEN the
  headline SHALL be exactly: `acceptance: no checks evaluated`.
- WHEN `passed` is true THEN the headline SHALL be:
  `acceptance: PASS (generalization_gap {gap}, all {n} checks passed)`.
- OTHERWISE the headline SHALL list failed check names:
  `acceptance: FAIL ({failed}/{total} checks failed: ...)`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_acceptance()` SHALL NOT mutate its input report.

## Verification

- `tests/test_spec_015_acceptance.py` exercises each EARS block above.
- Broader coverage (CLI, realistic artifacts) remains in `tests/test_acceptance.py`.
