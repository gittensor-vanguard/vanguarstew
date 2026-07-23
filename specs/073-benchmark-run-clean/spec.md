# Spec 073 — run-clean gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1918
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/run_clean.py`](../../benchmark/run_clean.py) (the gate under test),
  [`benchmark/comparability.py`](../../benchmark/comparability.py) (`artifact_kind`, its only
  dependency), [`benchmark/acceptance.py`](../../benchmark/acceptance.py) (`_partition_error`, whose
  per-repo error convention this mirrors), [`scripts/run_clean.py`](../../scripts/run_clean.py) (the
  CI entry point)

This spec makes the **existing, implicit** run-clean contract explicit. It describes the as-built
behavior of `benchmark/run_clean.py`; it introduces **no behavior change**.

The module's only dependency is `benchmark.comparability.artifact_kind(artifact)`, which classifies
a replay artifact as `"single"`, `"multi"`, `"generalization"`, or `"invalid"`. This spec relies on
that classification only through those return values and does not otherwise constrain it.

## Why

`acceptance` and `promotion` embed error checks inside broader criteria. `check_run_clean` is the
minimal pass/fail gate for the common CI question: did this run finish without an `error` on the
artifact, its generalization partitions, or any `per_repo` row? It fails **closed** on a malformed
artifact so a broken run can't be reported clean.

## User stories

1. **As a CI maintainer**, I can gate a run on `scripts/run_clean.py` and log a stable
   `run_clean_headline()` OK/ERRORS line.
2. **As a benchmark operator**, I can trust OK means no error was recorded anywhere the run records
   one — top level, either generalization partition, or a per-repo row (including a corrupt
   string row).
3. **As a reviewer**, every artifact-shape, malformed-row, warning and headline branch is written
   down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Warnings

Where this spec says a helper "warns", the delivery is a single `logging.warning` call on the
module logger `benchmark.run_clean` (`logger = logging.getLogger(__name__)`); no exception is
raised and the sanitized value is still returned. The message content is pinned per case below and
is asserted via `caplog` in the contract tests.

## Constants

- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Helpers

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_is_passed(value)` SHALL be true for a Python `bool` (via `isinstance`, so a `bool` subclass is
  accepted) and a `numpy` scalar boolean (`type(value).__name__` in `bool_`/`bool8`/`bool`), and
  SHALL reject `int` `0`/`1`.
- `_check_row_field("name", value)` SHALL require a non-empty `str`; `_check_row_field("passed",
  value)` SHALL require `_is_passed`.

### Error scan (`_partition_errors`)

- WHEN the artifact carries a truthy top-level `error` THEN the findings SHALL include
  `"top-level error: {error!r}"`.
- WHEN `artifact_kind` is `"generalization"` THEN for each of `tuned`/`held_out` a truthy partition
  `error` SHALL add `"{part} error: {err!r}"`, and both partitions' `per_repo` lists SHALL be
  scanned (labelled `tuned`/`held_out`).
- WHEN `artifact_kind` is `"multi"` THEN the top-level `per_repo` SHALL be scanned (labelled
  `multi`).
- OTHERWISE (single/invalid) no `per_repo` SHALL be scanned (only the top-level `error`, if any).
- For each scanned `per_repo` list (a non-list `per_repo` is skipped): a dict row with a truthy
  `error` SHALL add `"{label}.per_repo[{repo}] error: {error!r}"` where `repo` is the row's `repo`,
  else `repo_name`, else its index; a **non-empty string** row SHALL add
  `"{label}.per_repo[{idx}] malformed row: {row!r}"`. Empty/whitespace strings and other
  non-dict/non-string entries SHALL be ignored.

### Gate (`check_run_clean`)

- WHEN `result` is not a dict THEN findings SHALL be `["artifact is not a JSON object"]` and
  `artifact_kind` in the result SHALL be `"invalid"`.
- OTHERWISE findings SHALL be `_partition_errors(result)` and `artifact_kind` SHALL be
  `artifact_kind(result)`.
- The result SHALL carry a single `no_errors` check whose `passed` is `not findings` and whose
  `detail` is `"no errors recorded"` when clean, else `"; ".join(findings)`.
- The result SHALL always carry `passed` (`not findings`), `checks`, `findings`, `artifact_kind`.

### Checks-row sanitation (`_check_rows_list`) and findings (`_findings_list`)

- WHEN `checks` is `None` THEN `_check_rows_list` SHALL return `[]` **silently** (no warning).
- WHEN `checks` is not a list THEN it SHALL return `[]` after a `logging.warning` of the form
  `run_clean: checks is {type}, not a list; treating as empty`.
- A row SHALL be skipped after a `logging.warning` when it is not a dict
  (`... checks[{i}] is {type}, not an object; skipping`), is missing a `_CHECK_ROW_KEYS` key
  (`... missing required key(s) {keys}; skipping`), or has an unusable `name`/`passed`
  (`... {key} is {detail}, not a usable {expected}; skipping`, where `passed`'s expected is `bool`
  and `name`'s is `non-empty str`).
- WHEN `checks` is a non-empty list but no row survives THEN a `logging.warning`
  `run_clean: checks had {n} entr{y|ies} but no usable rows` SHALL be logged.
- WHEN `findings` is `None` THEN `_findings_list` SHALL return `[]` silently; WHEN it is a non-list
  THEN `[]` after a `logging.warning` `run_clean: findings is {type}, not a list; treating as
  empty`; otherwise the list unchanged (findings are free-form strings, counted as-is).

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized check whose `passed` is falsy.
- WHEN `result.passed` is truthy THEN `run_clean_headline` SHALL be
  `run clean: OK ({artifact_kind})`.
- OTHERWISE it SHALL be `run clean: ERRORS ({n} finding(s))` where `n` is `len(_findings_list(...))`.

### Pure evaluation

- The module SHALL perform no I/O (beyond the logging warnings above).
- `check_run_clean()` SHALL NOT mutate its input, and a non-dict `result` SHALL fail closed rather
  than raise.

## Out of scope

- The broader gates that embed error checks (`acceptance`, `promotion`).
- `artifact_kind`'s own classification rules (`comparability`).

## Verification

- `tests/test_spec_073_run_clean.py` exercises each EARS block above, pinning **literal** expected
  findings, `passed` values and detail/headline strings, and asserting the non-list-`checks`,
  all-unusable, and non-list-`findings` warnings via `caplog`. Values use `repr` that is stable
  across platforms.
- Broader coverage (including the CLI) remains in `tests/test_run_clean.py`.
