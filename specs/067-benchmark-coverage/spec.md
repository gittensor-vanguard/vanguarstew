# Spec 067 — multi-repo coverage gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1898
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/coverage.py`](../../benchmark/coverage.py) (the gate under test),
  [`benchmark/acceptance.py`](../../benchmark/acceptance.py) (how *well* a run scored),
  [`benchmark/sample_adequacy.py`](../../benchmark/sample_adequacy.py) (per-repo task adequacy),
  [`scripts/repo_coverage.py`](../../scripts/repo_coverage.py) (the CI entry point)

This spec makes the **existing, implicit** coverage contract explicit. It describes the as-built
behavior of `benchmark/coverage.py`; it introduces **no behavior change**.

## Why

`run_multi_replay` keeps zero-task repos in `per_repo` and excludes them from the aggregate, so a
run can silently shrink to one scored repo (four of five skipped) and still report a headline
`composite_mean`. The acceptance and promotion gates check *how well* a run scored; nothing else
checks it covered **enough breadth**. `check_coverage` gates breadth: enough repos scored, not too
many skipped, enough total tasks — over both a multi-repo `per_repo` list and a `--generalization`
report's two partitions.

## User stories

1. **As a CI maintainer**, I can gate a run on breadth (`scripts/repo_coverage.py`) alongside
   `--fail-under` and the acceptance/promotion gates, and log a stable `coverage_headline()`.
2. **As a benchmark operator**, I can trust that a SUFFICIENT verdict means real per-repo detail
   with enough scored repos and tasks, not a run that quietly collapsed to one repo.
3. **As a reviewer**, every malformed-input, single-repo, corrupt-row and headline branch is written
   down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `DEFAULT_MIN_REPOS` SHALL be `2`, `DEFAULT_MAX_SKIPPED` SHALL be `1`, `DEFAULT_MIN_TASKS` SHALL
  be `3`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Helpers

- `_is_number(value)` SHALL be true only for a non-boolean, finite `int`/`float`; a `NaN`/`inf`
  SHALL be false, and an oversized `int` (`math.isfinite` raising `OverflowError`) SHALL be false.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_per_repo_list(items)` SHALL return `items` when it is a list, `[]` when it is `None` (silent),
  and `[]` with a warning otherwise.
- `_repo_tasks(entry)` SHALL return `int(entry["tasks"])` when `entry` is a dict with a `_is_number`
  `tasks`, otherwise `None`.

### Per-repo collection (`_collect_per_repo_entries`)

- WHEN `result` carries a `per_repo` key THEN it SHALL return `(_per_repo_list(per_repo), "multi")`.
- OTHERWISE WHEN `result` has a truthy `tuned`/`held_out` dict or a `generalization_gap` key THEN it
  SHALL return the concatenation of both partitions' `per_repo` lists with source
  `"generalization"`.
- OTHERWISE it SHALL return `([], "none")`.

### Counting (`_partition_counts`, `_total_scored_tasks`)

- For each entry, a dict with a `_is_number` `tasks` SHALL add to `total`, and to `scored` when
  `tasks > 0` else to `skipped`.
- A **non-empty string** entry SHALL count as one `total` and one `skipped` repo (a corrupt row is a
  real repo that produced no scored tasks, so it must not be silently dropped and inflate the pass
  rate); empty/whitespace strings and other non-dict/non-string entries SHALL be ignored.
- `_total_scored_tasks` SHALL sum `tasks` over entries whose `tasks` is `_is_number` and `> 0`.

### Gate (`check_coverage`)

- The result SHALL always carry `passed`, `checks`, `source`, `repos_total`, `repos_scored`,
  `repos_skipped`, `total_tasks`, `min_repos`, `max_skipped`, `min_tasks`.
- Four checks SHALL be added in order: `is_multi_repo`, `min_repos_scored`, `max_skipped`,
  `min_tasks`.
- `is_multi_repo` SHALL pass when `source != "none"`.
- WHEN the artifact is multi-repo THEN `min_repos_scored` SHALL pass when `repos_scored >=
  min_repos`, `max_skipped` when `repos_skipped <= max_skipped`, and `min_tasks` when `total_tasks
  >= min_tasks`, each with a detail naming the count and threshold.
- WHEN the artifact is NOT multi-repo THEN the three breadth checks SHALL carry detail
  `"not applicable (single-repo artifact)"` and SHALL be forced to `passed = False` (a single-repo
  artifact is out of scope for a breadth gate and fails it).
- `passed` SHALL be `all(c["passed"] for c in checks)`.

### Checks-row sanitation (`_check_rows_list`)

- `None` / non-list `checks` SHALL yield `[]` (with a warning for the non-list case).
- A row SHALL be skipped (with a warning) when it is not a dict, is missing `name`/`passed`, has a
  non-`str` `name`, or a `passed` whose `type(...) is not bool` (an `int` `0`/`1` is rejected).
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized check whose `passed` is falsy.
- WHEN no sanitized checks exist THEN `coverage_headline` SHALL be exactly
  `coverage: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be
  `coverage: SUFFICIENT ({repos_scored} scored repo(s), {total_tasks} task(s))`.
- OTHERWISE it SHALL be `coverage: INSUFFICIENT ({f}/{n} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_coverage()` SHALL NOT mutate its input.

## Out of scope

- The score/quality gates (`acceptance`, `promotion`) and per-repo task adequacy
  (`sample_adequacy`).
- Tuning the default thresholds.

## Verification

- `tests/test_spec_067_coverage.py` exercises each EARS block above, pinning **literal** expected
  check names, `passed` values and detail strings.
- Broader coverage (including the CLI) remains in `tests/test_coverage.py`.
