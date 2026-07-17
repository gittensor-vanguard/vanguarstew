# Spec 062 — blend weight integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #1789
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/row_integrity.py`](../../benchmark/row_integrity.py) (row composite vs
  headline, Spec 029), [`benchmark/score_integrity.py`](../../benchmark/score_integrity.py)
  (composite blend, Spec 059),
  [`benchmark/objective_integrity.py`](../../benchmark/objective_integrity.py) (anchor inputs,
  Spec 061)

This spec makes the **existing, implicit** blend-weight contract explicit. It describes the
as-built behavior of `benchmark/weight_integrity.py`; it introduces **no behavior change**.

## Why

`run_replay` records the `weights` used to blend the judge and objective components into each
task's `composite`. `row_integrity` and `score_integrity` *consume* those weights when verifying
scores, but nothing checks that the weights themselves are sound. A hand-edited artifact could
omit `weights` or declare a zero-sum (or negative) blend, silently changing every downstream
composite while still passing the score checks that trust the declared weights.

Spec 061 (`objective_integrity`) closed the anchor-input gap; this closes the blend-weight gap,
leaving `judge_report_integrity` as the last undocumented `benchmark/*integrity*.py` module.

## User stories

1. **As a benchmark operator**, I can trust that a VALID verdict means every scored slice
   declared finite, non-negative weights that actually sum to something.
2. **As a CI maintainer**, I can gate on `scripts/weight_integrity.py` and log a stable
   `integrity_headline()` string.
3. **As a reviewer**, every malformed-input, empty-slice, early-return and headline branch is
   written down (addressing the incompleteness class of rejection seen on Specs 057/059).

## Constants

- `_CHECK_ROW_KEYS` SHALL be `("name", "passed")`.
- The module SHALL expose no tolerance constant; `check_weight_integrity` takes no tolerance and
  its result SHALL carry only `passed` and `checks` (unlike Spec 061's result, which also carries
  `tolerance`).

## Acceptance criteria (EARS)

### Numeric helper (`_is_number`) — deliberately stricter than its siblings

A weight is the multiplier the whole blend trusts, so this helper is **type-exact**:

- `_is_number(value)` SHALL be true only when `type(value)` is exactly `int` or `float` **and**
  `math.isfinite(value)`.
- WHEN `value` is a `bool` THEN it SHALL be false (`type` is `bool`, not `int`).
- WHEN `value` is a `numpy` scalar (e.g. `numpy.float64`, whose `type` is never plain `float`)
  THEN it SHALL be false — unlike the `isinstance`-based helpers in the sibling integrity
  modules.
- WHEN `value` is `NaN` / `inf` / `-inf` THEN it SHALL be false.
- WHEN `value` is an `int` too large to convert to a float (`math.isfinite` raising
  `OverflowError`, as `json.load` produces from an oversized integer literal) THEN it SHALL be
  false rather than raising.
- WHEN `value` is a `str`, `None`, list, or dict THEN it SHALL be false.

### Dict / per_repo coercion

- `_dict(value)` SHALL return `value` when it is a `dict`, otherwise `{}`.
- WHEN `items` is `None` THEN `_per_repo_list` SHALL return `[]` **without** a container warning
  (an absent key is not malformed).
- WHEN `items` is an empty list THEN it SHALL return `[]` without a warning (zero repos recorded).
- WHEN `items` is a non-list THEN it SHALL log a warning and return `[]` (never coerced).
- `_per_repo_list` SHALL keep only `dict` entries, skipping (and warning on) each non-dict entry.

### Scored-slice predicates

- `_scored_repo(entry)` SHALL be true only when `_is_number(entry["tasks"])` and
  `int(tasks) > 0`.
- `_partition_scored(partition)` SHALL coerce a non-dict partition via `_dict` and then be true
  when: any `per_repo` row is `_scored_repo`; OTHERWISE when `scored_repos` passes `_is_number`,
  its `int(...) > 0`; OTHERWISE when `tasks` passes `_is_number` and `int(tasks) > 0`. A
  partition that omits `scored_repos` but records scored `per_repo` work SHALL still be scored.

### Slice selection (`_expand_slice`, `_weight_slices`)

- WHEN a partition carries a list `per_repo` THEN `_expand_slice` SHALL yield one slice per
  `_scored_repo` row, labelled `{label}:repo-{index}`; OTHERWISE it SHALL yield the partition
  itself as `(label, part)`.
- WHEN `result` carries dict `tuned` and `held_out` AND a `generalization_gap` key THEN each
  `_partition_scored` partition SHALL contribute its slices, labelled `tuned` / `held_out`.
- OTHERWISE WHEN `result` has a `per_repo` key THEN each `_scored_repo` entry SHALL be a slice
  labelled `repo-{index}` (an unscored or empty `per_repo` therefore yields **no** slices).
- OTHERWISE `_weight_slices` SHALL return exactly `[("run", result)]` — so a bare `{}` is a
  single `run` slice, not an empty selection.

### Per-slice checks (`_check_slice`)

For a slice labelled `L`, check names SHALL be prefixed `L:` unless `L == "run"`.

- WHEN `weights` is not a `dict` THEN a single failing `weights_present` SHALL be added with
  detail `"weights is {kind}, expected an object with judge/objective"`, where `kind` is
  `"absent"` for `None` else `"a {type}"`, and the slice SHALL add **no further checks**
  (early return).
- OTHERWISE `weights_present` SHALL pass only when both `"judge"` and `"objective"` are keys of
  `weights`, with detail `"judge {present|missing}, objective {present|missing}"`.
- `weights_non_negative` SHALL pass only when each of `judge` / `objective` passes `_is_number`
  and is `>= 0`; each offender SHALL be listed as `{name}={value!r}`, detail
  `"invalid component(s): {list}"`, else `"judge and objective are finite non-negative numbers"`.
- WHEN any component is invalid THEN `weights_sum_positive` SHALL be added as failing with detail
  `"cannot sum weights: one or both components are invalid"` and the slice SHALL add no further
  checks (early return).
- OTHERWISE `weights_sum_positive` SHALL pass only when `float(judge) + float(objective) > 0`,
  with detail `"judge + objective = {total} ({positive|not positive})"`.

### Top-level result (`check_weight_integrity`)

- WHEN `result` is not a `dict` THEN the result SHALL be `{"passed": False, "checks": [...]}`
  carrying only a failing `artifact_shape` with detail
  `"artifact must be a JSON object, got {type}"`, and slices SHALL NOT be evaluated.
- WHEN `_weight_slices` yields nothing THEN a failing `artifact_shape` SHALL be added with detail
  `"no scored replay slice with blend weights to verify"`.
- The returned mapping SHALL carry exactly `passed` and `checks`; `passed` SHALL be
  `all(c["passed"] for c in checks)`.

### Check-row sanitation

- `_is_passed(value)` SHALL be true for a `bool` (including subclasses) and for a `numpy` scalar
  bool (`type(...).__name__` in `("bool_", "bool8", "bool")`), and SHALL be false for `int`
  `0`/`1`. (Note the deliberate asymmetry with `_is_number`, which *rejects* numpy scalars: a
  weight must be an exact Python number, whereas a check row's verdict may legitimately arrive as
  a numpy bool.)
- `_check_row_field("name", v)` SHALL be true only for a non-empty (post-`strip`) `str`;
  `_check_row_field("passed", v)` SHALL be `_is_passed(v)`; any other key SHALL be false.
- `_check_rows_list` SHALL return `[]` for `None` and for an empty list, both silently.
- WHEN `checks` is a non-list THEN it SHALL warn and return `[]`.
- A row SHALL be skipped with a warning when it is not a dict, is missing any `_CHECK_ROW_KEYS`
  key, or fails `_check_row_field` for `name` or `passed`.
- WHEN `checks` is non-empty but no row survives THEN a warning SHALL be logged.

### Failed checks and headline

- `failed_checks(result)` SHALL return the `name` of every sanitized row whose `passed` is falsy,
  over `_dict(result).get("checks")`.
- WHEN no sanitized checks exist THEN `integrity_headline` SHALL be exactly:
  `weight integrity: no checks evaluated`.
- WHEN `result.passed` is truthy THEN it SHALL be:
  `weight integrity: VALID ({n} checks passed)`.
- OTHERWISE it SHALL be:
  `weight integrity: INVALID ({f}/{n} checks failed: {names})`.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_weight_integrity()` SHALL NOT mutate its input.

## Out of scope

- Choosing or validating the *right* blend weights (`--w-judge` / `--w-objective` policy).
- The composite blend itself (`score_integrity`, Spec 059) and row/headline agreement
  (`row_integrity`, Spec 029).
- `judge_report_integrity`, the remaining undocumented integrity module.

## Verification

- `tests/test_spec_062_weight_integrity.py` exercises each EARS block above, including the strict
  `_is_number` rejections (bool / numpy / non-finite / oversized int), both early returns, empty
  and unscored slices, the `_is_passed` vs `_is_number` asymmetry, and every headline branch.
- Broader coverage (including the CLI) remains in `tests/test_weight_integrity.py`.
