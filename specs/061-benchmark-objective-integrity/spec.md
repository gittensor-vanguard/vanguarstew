# Spec 061 — objective anchor integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1739
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/score.py`](../../benchmark/score.py) (`objective_component`, the anchor
  under test), [`benchmark/row_integrity.py`](../../benchmark/row_integrity.py) (row composite vs
  headline), [`benchmark/score_integrity.py`](../../benchmark/score_integrity.py) (composite blend,
  Spec 059), [`benchmark/gap_integrity.py`](../../benchmark/gap_integrity.py) (Spec 027)

This spec makes the **existing, implicit** objective-integrity contract explicit. It describes the
as-built behavior of `benchmark/objective_integrity.py`; it introduces **no behavior change**.

## Why

`row_integrity` verifies that row composites and headline means agree; `score_integrity` verifies
the composite blend. Neither checks that each row's `objective` dict is a **valid anchor input**.
A malformed artifact can carry a non-ratio or boolean recall and still pass those gates, which
trust component means that are already corrupted. This gate fails **loudly** on such an artifact
instead of scoring a plausible-but-wrong anchor.

### Recorded discrepancy — the module docstring's inflation claim is stale

`benchmark/objective_integrity.py:5-8` motivates the gate by saying a malformed artifact "can
carry `weighted_module_recall: true` and **inflate** the objective anchor via
`float(True) == 1.0` (#1233)". That is **not** the as-built behavior:

```
$ python -c "from benchmark.score import objective_component; print(objective_component({'weighted_module_recall': True}))"
0.0
```

`score._recall_for_component` rejects bools and falls back to `module_recall`, else `0.0` — and it
landed in the same commit that added this gate (`4f43859`, #1239). So a bool recall is silently
**floored to 0.0 (deflation)**, never inflated to 1.0, in every code state where this module has
existed. This spec documents the as-built behavior; the gate's real value is failing loudly rather
than scoring a quietly-deflated anchor. The docstring claim is recorded here as a discrepancy and
is **not** transcribed as contract.

## User stories

1. **As a benchmark operator**, I can trust that a CONSISTENT verdict means every scored row's
   objective inputs were valid ratios, not silently-floored junk.
2. **As a CI maintainer**, I can gate on `scripts/objective_integrity.py` and log a stable
   `integrity_headline()` string.
3. **As a reviewer**, every malformed-input, empty-slice, truncation and headline branch is
   written down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `DEFAULT_TOLERANCE` SHALL be `0.002`.
- `_RECALL_KEYS` SHALL be `("weighted_module_recall", "module_recall")`.
- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.

## Acceptance criteria (EARS)

### Numeric helpers

- `_is_number(value)` SHALL be true only for non-boolean `int`/`float` values that are finite;
  an oversized `int` (`math.isfinite` raising `OverflowError`) SHALL be false.
- `_is_ratio(value)` SHALL be true only when `_is_number(value)` and `0.0 <= float(value) <= 1.0`.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- `_round3(value)` SHALL return `round(float(value), 3)` when `_is_number(value)`, else `None`.
- `_mean(values)` SHALL return `None` for an empty list, else `_round3` of the arithmetic mean.

### Row / per_repo coercion

- WHEN `rows` is `None` THEN `_rows_list` SHALL return `[]`.
- WHEN `rows` is not a list THEN `_rows_list` SHALL log a warning and return `[]`.
- `_rows_list` SHALL keep only `dict` rows, skipping (and warning on) each non-dict entry.
- `_per_repo_list` SHALL apply the same `None` / non-list / non-dict-entry coercion.

### Slice selection (`_row_slices`, `_expand_slice`)

- WHEN `result` carries dict `tuned` and `held_out` AND a `generalization_gap` key THEN each
  partition that is scored SHALL contribute its slices, labelled `tuned` / `held_out`.
- WHEN a partition (or the top-level result) carries `rows` THEN it SHALL be one slice; OTHERWISE
  its `per_repo` entries with `_is_number(tasks)`, `int(tasks) > 0` and non-`None` `rows` SHALL
  each contribute a slice labelled `{label}:repo-{index}`.
- WHEN `result` has `per_repo` (non-generalization) THEN each entry with a positive numeric
  `tasks` and non-`None` `rows` SHALL be a slice labelled `repo-{index}`.
- OTHERWISE WHEN `result.rows` is not `None` THEN the whole result SHALL be one slice labelled
  `run` (whose check names carry **no** prefix).
- OTHERWISE `_row_slices` SHALL return `[]`.

### Per-slice checks (`_check_slice`)

For a slice labelled `L`, check names SHALL be prefixed `L:` unless `L == "run"`.

- `rows_present` SHALL pass when at least one usable row dict exists; detail SHALL be
  `"{n} usable row(s)"`.
- `objectives_present` SHALL pass only when rows exist AND every row's `objective` is a dict;
  detail SHALL be `"{n} row(s) missing a dict objective"`, or `"no rows to verify"` when empty.
- `recall_fields_valid` SHALL pass only when rows exist AND no row reports a recall problem.
  For each `_RECALL_KEYS` key **present** in a row objective: a `bool` SHALL report
  `"{key} is bool"`; a non-ratio SHALL report `"{key}={value!r} is not a ratio in [0, 1]"`;
  an absent key SHALL be ignored. Passing detail SHALL be
  `"all recall fields are finite ratios in [0, 1]"`.
- `kind_recall_valid` SHALL be evaluated only when `objective.actual_kinds` is truthy; then
  `kind_recall` (default `0.0`) SHALL be a non-bool finite ratio, else report
  `"kind_recall is bool"` / `"kind_recall={value!r} is not a ratio in [0, 1]"`. It SHALL pass
  when there are no problems (including on an empty slice).
- `objective_mean_matches_rows` SHALL compare `composite_parts.objective_mean` to the `_mean` of
  `score.objective_component` over each dict `objective`; it SHALL pass only when both are
  available and `abs(delta) <= tolerance`. WHEN either side is unavailable THEN it SHALL fail
  with detail `"cannot compare objective_mean to row objective components"`.

### Detail truncation

- `recall_fields_valid` failure detail SHALL join at most the first **3** row problems with
  `"; "`, appending `" ..."` when more than 3 exist.
- `kind_recall_valid` failure detail SHALL join at most the first **3** row problems with `"; "`
  and SHALL NOT append an ellipsis.

### per_repo well-formedness (`_malformed_per_repo_rows`)

- WHEN the artifact carries no `per_repo` container (single-repo/rows-only) THEN it SHALL return
  `None` and the `per_repo_rows_wellformed` check SHALL NOT be added.
- WHEN a `per_repo` list exists THEN each entry that is a **non-empty string** SHALL be flagged
  `repo-{index}` (or `{partition}:repo-{index}` for generalization); dicts (including ones
  carrying their own `error`), ints, `None` and lists SHALL NOT be flagged.
- The `per_repo_rows_wellformed` check SHALL pass when no row is flagged, with detail
  `"all per_repo rows are well-formed result objects"`, else
  `"corrupt per_repo string row(s): {labels}"`.

### Top-level result (`check_objective_integrity`)

- WHEN `result` is not a `dict` THEN the result SHALL be
  `{"passed": False, "checks": [artifact_shape], "tolerance": tolerance}` with detail
  `"artifact must be a JSON object, got {type}"` and SHALL NOT evaluate slices.
- WHEN no scored slice with rows exists THEN a failing `artifact_shape` check SHALL be added with
  detail `"no scored replay slice with per-task rows to verify"`.
- The returned mapping SHALL always carry `passed`, `checks` and `tolerance`; `passed` SHALL be
  `all(c["passed"] for c in checks)` (vacuously `True` only if `checks` is empty).
- `tolerance` SHALL echo the caller's value.

### Checks-row sanitation (`_check_rows_list`)

- `None` / non-list `checks` SHALL yield `[]` (with a warning for the non-list case).
- A row SHALL be skipped (with a warning) when it is not a dict, is missing `name` or `passed`,
  has a non-`str` `name`, or a `passed` whose `type(...) is not bool` (so a numpy/`int` truthy
  value is rejected).
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized check whose `passed` is
  falsy, over `_dict(result).get("checks")`.
- WHEN no sanitized checks exist THEN `integrity_headline` SHALL be exactly:
  `objective integrity: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be:
  `objective integrity: VALID ({n} checks passed)`.
- OTHERWISE it SHALL be:
  `objective integrity: INVALID ({f}/{n} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_objective_integrity()` SHALL NOT mutate its input.

## Out of scope

- Changing `score.objective_component` semantics or the recall/anchor definition.
- The composite blend (`score_integrity`, Spec 059) and row/headline agreement
  (`row_integrity`, Spec 029).
- Correcting the stale docstring claim (recorded above; no behavior change here).

## Verification

- `tests/test_spec_061_objective_integrity.py` exercises each EARS block above, pinning
  **literal** expected anchor values rather than re-deriving them from `objective_component`,
  and covers constants, empty slices, detail truncation and every headline branch.
- Broader coverage (including the CLI) remains in `tests/test_objective_integrity.py`.
