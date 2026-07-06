# Spec 018 — the offline objective-scoring calibration harness

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #801
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/002-scoring-anchor`](../002-scoring-anchor/spec.md) (objective anchor under test),
  [`benchmark/score_corpus/`](../../benchmark/score_corpus/) (shipped golden scenarios)

This spec makes the **existing, implicit** score-calibration contract explicit. It describes the
as-built behavior of `benchmark/score_calibration.py`; it introduces **no behavior change**. The
shipped corpus verifies offline objective scoring and composite blending — so validation, loading,
numeric matching, and headline helpers must be written down and verified.

## Why

Offline CI depends on the score corpus staying aligned with `objective_score` / `objective_component`
/ `composite_score` rules. A malformed scenario file or calibration result must fail closed or
degrade gracefully rather than crashing the runner. Legitimate **zero** scores (for example
`module_recall: 0.0`) must be distinguishable from missing fields. Making that contract explicit
lets reviewers check calibration harness changes against intent.

## User stories

1. **As a benchmark maintainer**, I can load and validate the shipped score corpus and know
   exactly which fields each scenario must carry — so bad fixtures are caught before CI runs.
2. **As a CI operator**, I can run `check_calibration()` offline and read a stable pass/fail
   headline — so scoring regressions surface without git clones or live LLM calls.
3. **As a reviewer**, numeric matching (including zeros and non-finite values) and malformed-result
   handling are written down — so a change to `score_calibration.py` is checked against the spec.

## Acceptance criteria (EARS)

### Scenario validation

- `validate_scenario(data, where=...)` SHALL return a `list[str]` of human-readable errors; an
  empty list means the scenario is well-formed.
- IF `data` is not a `dict` THEN validation SHALL report that the scenario must be a JSON object.
- IF any required key is missing (`id`, `description`, `plan`, `revealed`, `expected`) THEN
  validation SHALL report the missing keys.
- `id` SHALL be a non-empty string.
- `expected` SHALL be a non-empty `dict`.
- IF `plan` is present and not a `list` THEN validation SHALL report an error.
- IF `revealed` is present and not a `list` THEN validation SHALL report an error.
- IF optional `winner` is present and not one of `A`, `B`, or `tie` THEN validation SHALL report
  an error.

### Manifest and corpus loading

- `load_manifest(path)` SHALL load a JSON object whose `scenarios` key is a non-empty `list`.
- Each manifest entry SHALL have non-empty string `id` and `file` fields.
- IF the manifest is not a JSON object or `scenarios` is missing/empty THEN loading SHALL raise
  `ValueError`.
- `load_scenario(path)` SHALL load one scenario file and run `validate_scenario`; IF validation
  fails THEN loading SHALL raise `ValueError` joining the errors.
- `load_corpus(root)` SHALL load every scenario listed in the manifest under `root`.
- IF a manifest `id` does not match the scenario file's `id` THEN loading SHALL raise `ValueError`.
- IF two manifest entries share the same scenario `id` THEN loading SHALL raise `ValueError`.

### Scenario replay

- `run_scenario(scenario, tolerance=...)` SHALL compute `objective_score` from the scenario's
  `plan` and `revealed` (plus optional kwargs) and compare each key in `expected`.
- The returned row SHALL include at least: `id`, `description`, `expected`, `actual`, `passed`, and
  `detail`.
- `passed` SHALL be `True` only when every expected field matches within `tolerance` (numeric) or
  exactly (bool).
- WHEN `winner` is `A`, `B`, or `tie` THEN `actual` SHALL also include `objective_component` and
  `composite_score` derived from the computed objective.

### Numeric matching

- WHEN an expected field is a finite numeric value and the actual value is also finite and within
  `tolerance` THEN the field SHALL match (including when both are **0.0** — a legitimate zero
  score, not a missing placeholder).
- WHEN an expected field is numeric and the actual value is missing (`None`) or not numeric THEN
  the field SHALL NOT match.
- WHEN an expected field is numeric and the actual value is non-finite (`NaN`, `+Inf`, `-Inf`)
  THEN the field SHALL NOT match (non-finite actuals fail closed).
- WHEN an expected field is `bool` THEN matching SHALL use identity (`True`/`False`), not numeric
  tolerance.
- `check_calibration(corpus, tolerance=...)` SHALL pass the same `tolerance` to every
  `run_scenario` call.

### Calibration aggregation

- `check_calibration(corpus, tolerance=...)` SHALL run every scenario in `corpus` (default: shipped
  corpus).
- The result SHALL include: `passed`, `scenario_count`, `results`, `failed`, and `tolerance`.
- `passed` SHALL be `True` only when every scenario row passes.
- `failed` SHALL list scenario ids that failed.
- The function SHALL NOT mutate the input `corpus` or scenario dicts.

### Malformed calibration-result robustness

- `failed_scenarios(result)` SHALL return `[]` when `result` is not a `dict`.
- WHEN `result["failed"]` is not a `list` THEN `_failed_ids_list()` SHALL treat it as empty and
  log a warning (not raise).
- WHEN `result["failed"]` contains non-string or blank entries THEN those entries SHALL be skipped;
  usable string ids SHALL still be returned.

### Calibration headline

- `calibration_headline(result)` SHALL return a one-line human summary prefixed with
  `score calibration:`.
- IF `result` is not a `dict` OR `scenario_count` is zero/missing THEN the headline SHALL read
  `score calibration: no scenarios evaluated`.
- WHEN `result["passed"]` is true THEN the headline SHALL include `PASS` and the scenario count.
- WHEN `result["passed"]` is false THEN the headline SHALL include `FAIL` and the failed scenario
  ids (when available).
- Malformed `failed` fields SHALL NOT crash headline formatting.

### Pure evaluation

- The module SHALL perform no network I/O.
- Loading and calibration SHALL never mutate scenario files, manifest data, or the input corpus
  list in place.

## Out of scope

- Changing objective-scoring rules (`benchmark/score.py`) — covered by spec 002.
- Adding or editing shipped corpus scenarios — separate maintenance PRs.
- Trend/headline score extraction (`benchmark/trend.py`) — separate module.

## Verification

- `tests/test_spec_018_score_calibration.py` (this PR) exercises each EARS block above against the
  real calibration harness.
- Broader corpus and CLI coverage remains in `tests/test_score_calibration.py`.
