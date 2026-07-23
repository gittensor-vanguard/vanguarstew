# Spec 072 — M3/M4 acceptance gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1916
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/acceptance.py`](../../benchmark/acceptance.py) (the gate under test, and the
  **definition** of `_partition_error`, which the other gates import),
  [`benchmark/generalization_gate.py`](../../benchmark/generalization_gate.py) (the same gap, a
  breadth gate), [`benchmark/gap_integrity.py`](../../benchmark/gap_integrity.py) (the reported gap's
  integrity, Spec 027), [`scripts/acceptance.py`](../../scripts/acceptance.py) (the CI entry point)

This spec makes the **existing, implicit** acceptance contract explicit. It describes the as-built
behavior of `benchmark/acceptance.py`; it introduces **no behavior change**. The module is
self-contained (its only import is `math`) and is the canonical definition of `_partition_error`;
this spec pins that helper's contract in full so downstream gates can reference it.

## Why

The M3/M4 acceptance run (ROADMAP.md) is an explicit, still-open deliverable: run `run_eval
--generalization` on the curated set and confirm it **completes clean** and the `generalization_gap`
is **reasonable**. Today that is a manual eyeballing of the JSON. `check_acceptance` makes it a
reproducible pass/fail gate, recomputing the gap from the two partition composites so a drifted
top-level `generalization_gap` cannot pass acceptance while integrity fails.

## User stories

1. **As a CI maintainer**, I can gate the acceptance run on `scripts/acceptance.py` and log a stable
   `acceptance_headline()` PASS/FAIL line.
2. **As a benchmark operator**, I can trust PASS means a generalization artifact that completed with
   no partition error, scored enough repos in both partitions, and has a computed gap within bound.
3. **As a reviewer**, `_partition_error`'s three error locations and truthiness rule, and every
   non-finite / placeholder / malformed-row / gap-not-computed branch, are written down (addressing
   the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `DEFAULT_MAX_GAP` SHALL be `0.15`, `DEFAULT_MIN_SCORED_REPOS` SHALL be `1`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Numeric helper (`_is_number`)

- `_is_number(value)` SHALL be true only for a value whose `type` is `int` or `float` (excluding
  `bool`) and whose `float(value)` is finite. Each of the following SHALL be **false**, evaluated
  independently:
  - a `bool` (`_is_number(True)` and `_is_number(False)`), because `isinstance(True, int)` is `True`
    in Python and a flag is not a count;
  - `math.nan` (`float("nan")`);
  - a positive infinity `math.inf` (`float("inf")`) and a negative infinity `-math.inf`;
  - a `str` such as `"2"`, and `None`.
- WHEN `value` is a Python `int` too large to convert to a `float` THEN `float(value)` raises
  `OverflowError`, which SHALL be caught and yield `False` (never propagate). This is exercised with
  `10 ** 400`; the assertion is portable because CPython's arbitrary-precision `int` makes `10 **
  400` an exact, platform-independent value that always exceeds `float` range.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### Partition error (`_partition_error`) — canonical definition

- WHEN `partition` is not a dict THEN it SHALL return `None`.
- WHEN the partition's top-level `error` is **truthy** (any Python-truthy value — a non-empty string,
  a non-zero number, a non-empty `dict`/`list`) THEN it SHALL return that `error` **value unchanged**
  (not a bool, not stringified), so callers can name the failure. A **falsy** `error`
  (`""`, `0`, `False`, `None`, `[]`, `{}`) SHALL NOT be treated as a failure.
- OTHERWISE WHEN `per_repo` is a list THEN, scanning in order, it SHALL return the first dict row's
  **truthy** `error` value (same truthiness rule, returned unchanged), else the first **non-empty
  string** row (a corrupt/malformed entry, returned as the string), else `None`.
- A non-list `per_repo`, non-dict/non-string rows, and empty/whitespace string rows SHALL contribute
  no error.

### Composite and gap (`_composite`, `_recomputed_gap`)

- `_composite(partition)` SHALL return `None` when `scored_repos` is `_is_number` and falsy (an
  unscored placeholder), else the `composite_mean` when `_is_number`, else `None`.
- `_recomputed_gap(tuned, held_out)` SHALL return `None` when either `_composite` is `None`, else
  `round(tuned_composite - held_out_composite, 3)`.

### Gate (`check_acceptance`)

- `report` SHALL be coerced with `_dict`; `tuned`/`held_out` SHALL be `_dict` of the corresponding
  keys; `gap` SHALL be `_recomputed_gap(tuned, held_out)`.
- The result SHALL always carry `passed`, `checks`, `generalization_gap`, `max_gap`,
  `min_scored_repos`; `generalization_gap` SHALL be `gap` when `_is_number(gap)` else `None`;
  `passed` SHALL be `all(c["passed"] for c in checks)`.
- Five checks SHALL be added in order: `is_generalization`, `no_partition_error`,
  `both_partitions_scored`, `gap_computed`, `gap_within_bound` — **every** check reported even after
  an earlier failure.
- `is_generalization` SHALL pass only when `report["tuned"]` and `report["held_out"]` are both dicts
  AND `"generalization_gap"` is a key of `report`.
- `no_partition_error` SHALL pass when neither partition's `_partition_error` is set; detail SHALL be
  `"both partitions completed without error"`, else
  `"partition error(s): tuned={tuned_err!r}, held_out={held_err!r}"`.
- `both_partitions_scored` SHALL pass when each partition's `scored_repos` is `_is_number` and `>=
  min_scored_repos`; detail SHALL be `"tuned scored {tuned_n}, held_out scored {held_n} (min {min})"`.
- `gap_computed` SHALL pass when `_is_number(gap)`; detail SHALL be `"generalization_gap = {gap}"`,
  else `"generalization_gap is not a number (a partition did not score)"`.
- `gap_within_bound` SHALL pass when `gap_computed and gap <= max_gap`; detail SHALL be
  `"gap {gap} <= max_gap {max}"` when within, `"gap {gap} exceeds max_gap {max}"` when computed but
  over, else `"gap not computed"`.

### Checks-row sanitation (`_check_rows_list`)

- WHEN `checks` is `None` THEN it SHALL return `[]` **silently**; WHEN it is not a list THEN `[]`
  after a `logging.warning` on the module logger `benchmark.acceptance`
  (`acceptance: checks is {type}, not a list; treating as empty`).
- A row SHALL be skipped after a warning when it is not a dict, is missing `name`/`passed`, has a
  non-`str` `name`, or a `passed` whose `type(...) is not bool` (a bool subclass and an `int` `0`/`1`
  are both rejected).
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized check whose `passed` (read via
  `.get("passed")`) is falsy.
- WHEN no sanitized checks exist THEN `acceptance_headline` SHALL be exactly
  `acceptance: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be
  `acceptance: PASS (generalization_gap {gap}, all {n} checks passed)`.
- OTHERWISE it SHALL be `acceptance: FAIL ({f}/{n} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O (beyond the sanitation logging warnings).
- `check_acceptance()` SHALL NOT mutate its input, and a non-dict `report` SHALL fail the checks
  rather than raise.

## Out of scope

- The reported gap's integrity (`gap_integrity`, Spec 027) and the breadth gate
  (`generalization_gate`).
- Tuning the default thresholds.

## Verification

- `tests/test_spec_072_acceptance.py` exercises each EARS block above, pinning **literal** expected
  check names, `passed` values and detail strings, with `_is_number`'s `nan`/`inf`/`-inf`/`bool`
  cases each asserted independently and the non-string-truthy `_partition_error` cases pinned, using
  values whose `repr` is stable across platforms.
- Broader coverage (including the CLI) remains in `tests/test_acceptance.py`.
