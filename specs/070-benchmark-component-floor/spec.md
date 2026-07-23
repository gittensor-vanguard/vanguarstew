# Spec 070 — per-component floor gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1912
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/component_floor.py`](../../benchmark/component_floor.py) (the gate under
  test), [`benchmark/promotion.py`](../../benchmark/promotion.py) (`_scored_composite`, the sibling
  placeholder guard), [`benchmark/acceptance.py`](../../benchmark/acceptance.py) (`_partition_error`),
  [`scripts/run_eval.py`](../../scripts/run_eval.py) (`check_score_floor`, the single-floor gate this
  strengthens), [`scripts/component_floor.py`](../../scripts/component_floor.py) (the CI entry point)

This spec makes the **existing, implicit** per-component floor contract explicit. It describes the
as-built behavior of `benchmark/component_floor.py`; it introduces **no behavior change**.

## Why

`run_eval --fail-under` gates the blended `composite_mean` against one floor. But the composite
blends the pairwise **judge** (trajectory/decision-process) and the deterministic **objective
anchor** (structural ground truth). A single composite floor lets an agent that wins the judge on
prose but barely moves the anchor slip through — the imbalance the anchor exists to catch.
`check_component_floors` gates each component independently, on the evaluated (top-level, or `tuned`
for a generalization) partition, and only when the run actually completed and scored.

## User stories

1. **As a CI maintainer**, I can gate each component on `scripts/component_floor.py` — stricter than
   `--fail-under` alone — and log a stable `component_floor_headline()` PASS/FAIL line.
2. **As a benchmark operator**, I can trust PASS means the run completed (no top-level or per-repo
   error), scored a real composite (an unscored placeholder `0.0` fails, not passes), and each of
   composite/judge/objective cleared its floor.
3. **As a reviewer**, every non-dict / non-finite / placeholder / error / generalization / headline
   branch is written down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `DEFAULT_MIN_COMPOSITE` SHALL be `0.5`, `DEFAULT_MIN_JUDGE` SHALL be `0.4`,
  `DEFAULT_MIN_OBJECTIVE` SHALL be `0.4`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Helpers

- `_is_number(value)` SHALL be true only for a non-boolean `int`/`float` whose `float(value)` is
  finite; a `NaN`/`inf` SHALL be false, and a `TypeError`/`OverflowError` from the conversion
  (e.g. an oversized `int`) SHALL yield false, never raise.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_floor_check(name, value, floor)` SHALL return `{"name", "passed", "detail"}` where `passed` is
  `_is_number(value) and value >= floor`, `detail` is `"{value} >= {floor}"` when `_is_number(value)`
  else `"value missing or non-numeric ({value!r})"`.
- `_scored_metric(result, key, nested_key=None)` SHALL read `result[key]` when `nested_key` is
  `None`, else `_dict(result[nested_key])[key]`; it SHALL return `None` when that value is not
  `_is_number`, `None` when `result["scored_repos"]` is `_is_number` and falsy (an unscored
  placeholder), otherwise the value. A result with no `scored_repos` key SHALL keep a genuine `0.0`.
- `_floor_source(result)` SHALL return the `tuned` partition when both `tuned` and `held_out` are
  dicts, otherwise `result` itself (a missing/`non-dict` `held_out` is NOT treated as generalization).
- `_artifact_error(result)` SHALL return the truthy top-level `error` when present; else the first
  `_partition_error` of `_floor_source(result)`; and WHEN `_partition_error` raises THEN it SHALL
  log a warning and return `"partition error scan failed"` (never propagate). A falsy top-level
  `error` (`0`/`False`/`""`/`None`) SHALL NOT be treated as a failure record.

### Gate (`check_component_floors`)

- The evaluated `source` SHALL be `_floor_source(result)`; `composite`/`judge`/`objective` SHALL be
  `_scored_metric` of `composite_mean`, `composite_parts.judge_mean`, `composite_parts.objective_mean`.
- `run_completed` SHALL be true only when `composite is not None` AND `_artifact_error(result) is
  None` (a real `0.0` composite counts as scored — completion SHALL NOT be `bool(composite)`).
- The result SHALL always carry `passed`, `checks`, `composite_mean`, `judge_mean`, `objective_mean`,
  `min_composite`, `min_judge`, `min_objective`; `passed` SHALL be `all(c["passed"] for c in checks)`.
- Four checks SHALL be added in order: `run_completed`, `composite_floor`, `judge_floor`,
  `objective_floor`.
- `run_completed` detail SHALL be `"run produced a scored composite"` when it passed, else
  `"no scored composite (error={error!r}, composite={composite!r})"`.
- `composite_floor`/`judge_floor`/`objective_floor` SHALL each be `_floor_check` of the
  corresponding metric against its floor (so a `None` metric fails with the "missing or non-numeric"
  detail).

### Checks-row sanitation (`_check_rows_list`)

- `None` / non-list `checks` SHALL yield `[]` (with a warning for the non-list case).
- A row SHALL be skipped (with a warning) when it is not a dict, or is missing `name`/`passed`.
  (Unlike some sibling gates, this sanitizer does NOT additionally reject a non-`str` `name` or a
  non-`bool` `passed`; a dict row carrying both keys is kept.)
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized check whose `passed` (read via
  `.get("passed")`) is falsy.
- WHEN no sanitized checks exist THEN `component_floor_headline` SHALL be exactly
  `component floors: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be
  `component floors: PASS (composite {composite_mean}, judge {judge_mean}, objective {objective_mean})`
  (each embedded as the raw stored value).
- OTHERWISE it SHALL be `component floors: FAIL ({f}/{n} below floor: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_component_floors()` SHALL NOT mutate its input, and a non-dict `result` SHALL fail the
  relevant checks rather than raise.

## Out of scope

- The single-composite floor (`run_eval.check_score_floor`) and the promotion decision
  (`promotion`).
- Tuning the default floors.

## Verification

- `tests/test_spec_070_component_floor.py` exercises each EARS block above, pinning **literal**
  expected check names, `passed` values and detail strings, using decimal literals whose `repr` is
  stable across platforms (e.g. `0.6`, `0.5`, `0.3`).
- Broader coverage (including the CLI) remains in `tests/test_component_floor.py`.
