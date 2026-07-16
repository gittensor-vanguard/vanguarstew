# Spec 027 — generalization gap integrity gate

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #887
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`benchmark/runner.py`](../../benchmark/runner.py) (`run_generalization_report` gap semantics),
  [`benchmark/acceptance.py`](../../benchmark/acceptance.py) (gap reasonableness gate)

This spec makes the **existing, implicit** gap-integrity contract explicit. It describes the
as-built behavior of `benchmark/gap_integrity.py`; it introduces **no behavior change**.
Generalization artifacts report `generalization_gap` from partition composites — that arithmetic
must be written down and verified before acceptance gates trust it.

## Why

`check_acceptance` gates whether a gap is *reasonable*; nothing verifies it was *computed correctly*
from `tuned.composite_mean` and `held_out.composite_mean`. Making the contract explicit lets
reviewers check gap-integrity changes against intent.

## User stories

1. **As a benchmark operator**, I can verify a `--generalization` artifact's gap matches its
   partition scores before trusting acceptance output.
2. **As a CI maintainer**, I can gate on `check_gap_integrity()` with a stable pass/fail headline.
3. **As a reviewer**, rounding semantics and malformed-input handling are written down.

## Acceptance criteria (EARS)

### Constants

- The module SHALL expose `DEFAULT_TOLERANCE = 0.0` as the default comparison bound for
  `check_gap_integrity(report, tolerance=...)`.

### Artifact shape

- WHEN `report` is not a `dict` THEN `check_gap_integrity(report)` SHALL return
  `{"passed": false, "checks": [...], "tolerance": ...}` with an `artifact_shape` check that
  fails (not raise).
- WHEN `report` lacks `tuned`, `held_out`, and `generalization_gap` THEN the gate SHALL fail
  `is_generalization` and SHALL NOT crash.

### Generalization structure

- `check_gap_integrity(report)` SHALL require `tuned` and `held_out` to be dicts and
  `generalization_gap` to be present on the artifact for `is_generalization` to pass.
- WHEN `is_generalization` fails THEN `passed` SHALL be `false`.

### Gap presence vs partition scoring

- WHEN either partition has `scored_repos == 0` (or non-numeric `scored_repos`) THEN
  `generalization_gap` SHALL be `None` for `gap_absent_when_unscored` to pass.
- WHEN both partitions have `scored_repos > 0` THEN `generalization_gap` SHALL be numeric for
  `gap_present_when_both_scored` to pass.
- WHEN both partitions scored THEN both partition `composite_mean` values SHALL be numeric for
  `tuned_composite_reported` and `held_out_composite_reported` to pass.

### Gap arithmetic

- `_expected_gap(tuned_mean, held_mean)` SHALL return `round(tuned_mean - held_mean, 3)` when both
  inputs are numeric; otherwise `None`.
- WHEN both partitions scored and composites are numeric THEN `gap_matches_partitions` SHALL pass
  only when `round(reported_gap, 3)` is within `tolerance` of `_expected_gap(...)`.
- `tolerance` SHALL default to `DEFAULT_TOLERANCE` (`0.0`).

### Gate result shape

- `check_gap_integrity()` SHALL return `{"passed", "checks", "tolerance"}` where `passed` is
  `True` only when every check passes.
- Each check SHALL carry `name`, `passed`, and `detail` keys.

### Malformed gate-result robustness

- WHEN `result["checks"]` is not a `list` THEN `_check_rows_list()` SHALL treat it as empty and
  log a warning (not raise).
- WHEN a check row is not a dict THEN that row SHALL be skipped with a warning.
- `failed_checks(result)` SHALL return names of usable rows with `"passed": false`.
- WHEN `checks` is missing, empty, or only unusable rows THEN `failed_checks()` SHALL return `[]`.

### Integrity headline

- `integrity_headline(result)` SHALL return a one-line summary.
- IF no usable checks remain after sanitization THEN the headline SHALL read
  `gap integrity: no checks evaluated`.
- WHEN `result["passed"]` is true THEN the headline SHALL include `CONSISTENT`.
- WHEN `result["passed"]` is false with usable checks THEN the headline SHALL include
  `INCONSISTENT` and failed check names.

### Pure evaluation

- The module SHALL perform no I/O.
- `check_gap_integrity()` SHALL NOT mutate its input dict.

## Out of scope

- Whether the gap is *acceptable* (`benchmark/acceptance.py`).
- Headline score extraction (`benchmark/trend.py`).
- Changing runner gap semantics.

## Verification

- `tests/test_spec_027_gap_integrity.py` (this PR) exercises each EARS block above.
- Broader CLI coverage remains in `tests/test_gap_integrity.py`.
