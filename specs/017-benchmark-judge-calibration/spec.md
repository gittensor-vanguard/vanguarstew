# Spec 017 — the offline pairwise-judge calibration harness

- **Status:** draft (SDD Phase 1 — Specify)
- **Owner:** benchmark
- **Issue:** #794
- **Constitution:** [`AGENTS.md`](../../AGENTS.md) → *Benchmark integrity (M1–M3)*
- **Methodology:** [`blog/spec-driven-development.md`](../../blog/spec-driven-development.md)
- **Related:** [`specs/004-pairwise-judge`](../004-pairwise-judge/spec.md) (ranking rules under test),
  [`benchmark/judge_corpus/`](../../benchmark/judge_corpus/) (shipped golden scenarios)

This spec makes the **existing, implicit** judge-calibration contract explicit. It describes the
as-built behavior of `benchmark/judge_calibration.py`; it introduces **no behavior change**. The
shipped corpus verifies offline pairwise-judge ranking and symmetry — so validation, loading,
aggregation, and headline helpers must be written down and verified.

## Why

Offline CI depends on the judge corpus staying aligned with `pairwise_judge` substance rules. A
malformed scenario file, manifest entry, or calibration result must fail closed or degrade
gracefully rather than crashing the runner. Making that contract explicit lets reviewers check
calibration harness changes against intent.

## User stories

1. **As a benchmark maintainer**, I can load and validate the shipped judge corpus and know
   exactly which fields each scenario must carry — so bad fixtures are caught before CI runs.
2. **As a CI operator**, I can run `check_calibration()` offline and read a stable pass/fail
   headline — so judge regressions surface without git clones or live LLM calls.
3. **As a reviewer**, symmetry checks and malformed-result handling are written down — so a change
   to `judge_calibration.py` is checked against the spec.

## Acceptance criteria (EARS)

### Scenario validation

- `validate_scenario(data, where=...)` SHALL return a `list[str]` of human-readable errors; an
  empty list means the scenario is well-formed.
- IF `data` is not a `dict` THEN validation SHALL report that the scenario must be a JSON object.
- IF any required key is missing (`id`, `description`, `context`, `revealed`, `submission_a`,
  `submission_b`, `expected_winner`) THEN validation SHALL report the missing keys.
- `id` SHALL be a non-empty string.
- `expected_winner` SHALL be one of `A`, `B`, or `tie`.
- IF `expected_winner` is any other value THEN validation SHALL report an error.

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

- `run_scenario(scenario, llm)` SHALL call `pairwise_judge` offline (default `LLM(api_key="offline")`)
  and compare the actual winner to `expected_winner`.
- The returned row SHALL include at least: `id`, `description`, `expected_winner`, `actual_winner`,
  `judge_order`, `passed`, and `detail`.
- `passed` SHALL be `True` only when `actual_winner == expected_winner`.

### Symmetry check

- WHEN `expect_symmetric` is absent or falsy THEN `check_symmetry(scenario, llm)` SHALL return
  `None` (symmetry is not evaluated).
- WHEN `expect_symmetric` is true THEN `check_symmetry()` SHALL run `pairwise_judge` with A/B
  submissions swapped.
- IF both forward and backward winners are `tie` THEN the symmetry check SHALL pass.
- IF forward and backward winners are decisive and opposite (`A` vs `B`) THEN the symmetry check
  SHALL pass.
- OTHERWISE the symmetry check SHALL fail.
- The symmetry row SHALL include `forward`, `backward`, `passed`, and `detail`.

### Calibration aggregation

- `check_calibration(corpus, llm)` SHALL run every scenario in `corpus` (default: shipped corpus)
  and optional symmetry checks.
- The result SHALL include: `passed`, `scenario_count`, `results`, `symmetry_checks`, and `failed`.
- `passed` SHALL be `True` only when every winner check passes AND every symmetry check passes
  (or there are no symmetry checks).
- `failed` SHALL list scenario ids that failed winner or symmetry checks.
- The function SHALL NOT mutate the input `corpus` or scenario dicts.

### Malformed calibration-result robustness

- `failed_scenarios(result)` SHALL return `[]` when `result` is not a `dict`.
- WHEN `result["failed"]` is not a `list` THEN `_failed_ids_list()` SHALL treat it as empty and
  log a warning (not raise).
- WHEN `result["failed"]` contains non-string or blank entries THEN those entries SHALL be skipped
  and a warning logged; usable string ids SHALL still be returned.
- WHEN `result["symmetry_checks"]` is not a `list` THEN `_symmetry_checks_list()` SHALL treat it
  as empty and log a warning (not raise).
- WHEN `symmetry_checks` contains non-dict rows THEN those rows SHALL be skipped with a warning.

### Calibration headline

- `calibration_headline(result)` SHALL return a one-line human summary.
- IF `result` is not a `dict` OR `scenario_count` is zero/missing THEN the headline SHALL read
  `calibration: no scenarios evaluated`.
- WHEN `result["passed"]` is true THEN the headline SHALL include `PASS` and the scenario count.
- WHEN `result["passed"]` is false THEN the headline SHALL include `FAIL` and the failed scenario
  ids (when available).
- Malformed `failed` or `symmetry_checks` fields SHALL NOT crash headline formatting.

### Pure evaluation

- The module SHALL perform no network I/O when using the default offline LLM.
- Loading and calibration SHALL never mutate scenario files, manifest data, or the input corpus
  list in place.

## Out of scope

- Changing pairwise-judge ranking rules (`benchmark/judge.py`) — covered by spec 004.
- Adding or editing shipped corpus scenarios — separate maintenance PRs.
- Online LLM calibration runs — the contract documents offline CI behavior.

## Verification

- `tests/test_spec_017_judge_calibration.py` (this PR) exercises each EARS block above against the
  real calibration harness.
- Broader corpus and CLI coverage remains in `tests/test_judge_calibration.py`.
