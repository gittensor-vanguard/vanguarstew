# Spec 062 — blend-weight integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1789
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/weight_integrity.py`](../../benchmark/weight_integrity.py) (the gate under
  test), [`benchmark/row_integrity.py`](../../benchmark/row_integrity.py) (row composite vs the
  declared weights, Spec 029), [`benchmark/score_integrity.py`](../../benchmark/score_integrity.py)
  (composite blend, Spec 059), [`benchmark/objective_integrity.py`](../../benchmark/objective_integrity.py)
  (anchor inputs, Spec 061)

This spec makes the **existing, implicit** blend-weight integrity contract explicit. It describes
the as-built behavior of `benchmark/weight_integrity.py`; it introduces **no behavior change**.

## Why

`run_replay` records the `weights` that blend the judge and objective components into each task's
`composite`. `row_integrity` and `score_integrity` *consume* those weights when verifying scores,
but neither checks that the weights themselves are sound. A hand-edited artifact could omit
`weights` or declare a zero-sum (or negative) blend and still pass the score checks that trust the
declared weights — silently changing every downstream composite. This gate fails **loudly** on such
an artifact, per scored replay slice.

## User stories

1. **As a benchmark operator**, I can trust that a VALID verdict means every scored slice declared a
   `weights` object whose `judge`/`objective` components are finite, non-negative, and sum to a
   positive blend.
2. **As a CI maintainer**, I can gate on `scripts/weight_integrity.py` and log a stable
   `integrity_headline()` string.
3. **As a reviewer**, every malformed-input, empty-slice, missing-component and headline branch is
   written down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.
- The module SHALL define no tolerance constant, and `check_weight_integrity` SHALL NOT echo a
  `tolerance` key (weights are compared exactly, not within a band).

## Acceptance criteria (EARS)

### Numeric helper (`_is_number`)

- `_is_number(value)` SHALL be true only when `type(value)` is exactly `int` or `float` **and** the
  value is finite. It is deliberately stricter than the `isinstance`-based sibling helper: a `bool`
  (`type is bool`), a `numpy` scalar (whose `type` is never plain `int`/`float`), and a non-finite
  `NaN`/`inf` SHALL all be false.
- WHEN `value` is a Python `int` too large to convert to a float (so `math.isfinite` raises
  `OverflowError`) THEN `_is_number` SHALL be false, not raise.
- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.

### per_repo coercion (`_per_repo_list`)

- WHEN `items` is `None` THEN it SHALL return `[]` with no warning.
- WHEN `items` is not a list THEN it SHALL log a warning and return `[]`.
- It SHALL keep only `dict` entries, skipping (and warning on) each non-dict entry.

### Scored-slice selection (`_scored_repo`, `_partition_scored`, `_expand_slice`, `_weight_slices`)

- `_scored_repo(entry)` SHALL be true only when `_is_number(entry["tasks"])` and `int(tasks) > 0`.
- `_partition_scored(partition)` SHALL be true when the partition's `per_repo` list holds at least
  one `_scored_repo`; ELSE when `scored_repos` is numeric, when `int(scored_repos) > 0`; ELSE when
  `tasks` is numeric, when `int(tasks) > 0` (a partition may omit `scored_repos` yet still record
  scored `per_repo` work — a missing key SHALL NOT skip the partition).
- `_expand_slice(label, part)` SHALL return one `({label}:repo-{index}, entry)` per `_scored_repo`
  entry when `part.per_repo` is a list, ELSE the single pair `(label, part)`.
- WHEN `result` carries dict `tuned` and `held_out` AND a `generalization_gap` key THEN
  `_weight_slices` SHALL return, for each partition that `_partition_scored`, its `_expand_slice`
  slices labelled `tuned` / `held_out`.
- OTHERWISE WHEN `result` has a `per_repo` key THEN each `_scored_repo` entry SHALL be a slice
  labelled `repo-{index}`.
- OTHERWISE the whole result SHALL be a single slice labelled `run`.

### Per-slice checks (`_check_slice`)

For a slice labelled `L`, check names SHALL be prefixed `L:` unless `L == "run"` (no prefix).

- WHEN `weights` is not a dict THEN a single `weights_present` check SHALL fail with detail
  `"weights is absent, expected an object with judge/objective"` when `weights is None`, else
  `"weights is a {type}, expected an object with judge/objective"`, and NO further check SHALL be
  added for the slice.
- `weights_present` SHALL pass only when the `weights` dict holds both `judge` and `objective` keys;
  detail SHALL be `"judge {present|missing}, objective {present|missing}"`.
- `weights_non_negative` SHALL pass only when each of `judge`/`objective` is `_is_number` and `>= 0`;
  a failing component SHALL be listed as `"judge={value!r}"` / `"objective={value!r}"`. Passing
  detail SHALL be `"judge and objective are finite non-negative numbers"`; failing detail SHALL be
  `"invalid component(s): {list}"`.
- WHEN either component is invalid THEN `weights_sum_positive` SHALL fail with detail
  `"cannot sum weights: one or both components are invalid"` and the sum SHALL NOT be computed.
- OTHERWISE `weights_sum_positive` SHALL pass only when `float(judge) + float(objective) > 0`, with
  detail `"judge + objective = {total} ({positive|not positive})"`.

### Top-level result (`check_weight_integrity`)

- WHEN `result` is not a `dict` THEN the result SHALL be
  `{"passed": False, "checks": [artifact_shape]}` with detail
  `"artifact must be a JSON object, got {type}"` and slices SHALL NOT be evaluated.
- WHEN no scored slice exists THEN a failing `artifact_shape` check SHALL be added with detail
  `"no scored replay slice with blend weights to verify"`.
- The returned mapping SHALL always carry `passed` and `checks`; `passed` SHALL be
  `all(c["passed"] for c in checks)`.

### Checks-row sanitation (`_check_rows_list`, `_is_passed`, `_check_row_field`)

- `_is_passed(value)` SHALL be true for a Python `bool` (or subclass) and a `numpy` scalar bool
  (`type(...).__name__` in `bool_`/`bool8`/`bool`), and SHALL reject `int` `0`/`1`.
- `_check_row_field("name", value)` SHALL require a non-empty `str`; `_check_row_field("passed",
  value)` SHALL require `_is_passed`.
- `None` / non-list `checks` SHALL yield `[]` (with a warning for the non-list case).
- A row SHALL be skipped (with a warning) when it is not a dict, is missing `name` or `passed`, has
  a non-`str` or empty `name`, or a `passed` that is not a bool.
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized check whose `passed` is falsy,
  over `_dict(result).get("checks")`.
- WHEN no sanitized checks exist THEN `integrity_headline` SHALL be exactly
  `weight integrity: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be `weight integrity: VALID ({n} checks passed)`.
- OTHERWISE it SHALL be `weight integrity: INVALID ({f}/{n} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_weight_integrity()` SHALL NOT mutate its input.

## Out of scope

- Changing how `row_integrity` / `score_integrity` consume the weights, or the composite blend
  definition (`score_integrity`, Spec 059).
- Verifying that the declared weights match a specific policy value (e.g. `0.6`/`0.4`); this gate
  checks soundness (present, non-negative, positive-sum), not a particular blend.

## Verification

- `tests/test_spec_062_weight_integrity.py` exercises each EARS block above, pinning **literal**
  expected check names, `passed` values and detail strings rather than re-deriving them.
- Broader coverage (including the CLI) remains in `tests/test_weight_integrity.py`.
