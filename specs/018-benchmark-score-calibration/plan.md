# Plan 018 — offline objective-scoring calibration harness

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #801

How the [spec](./spec.md) maps onto `benchmark/score_calibration.py` as-built. No new product
code; this records the contract surface so future calibration changes are reviewed against a plan.

## Architecture / control flow

```
validate_scenario(data) → list[str] errors

load_manifest(path) → dict
load_scenario(path) → dict (raises on validation errors)
load_corpus(root) → list[dict]

run_scenario(scenario, tolerance)
  ├─ objective_score(plan, revealed, **kwargs)
  ├─ objective_component / composite_score when winner set
  └─ compare each expected key via _values_match

check_calibration(corpus, tolerance)
  └─ aggregate passed / failed ids

failed_scenarios(result) → list[str]
calibration_headline(result) → str
```

## Numeric matching rules (`_values_match`)

| Expected | Actual | Match? |
| -------- | ------ | ------ |
| finite number | finite within tolerance | yes (including 0.0 == 0.0) |
| finite number | `None` or non-numeric | no |
| finite number | NaN / ±Inf | no |
| bool | same bool identity | yes |
| other | equality | yes |

## EARS → test mapping

| Spec section | Test group in `test_spec_018_score_calibration.py` |
| ------------ | ------------------------------------------------- |
| Scenario validation | `test_validate_scenario_*` |
| Manifest and corpus loading | `test_load_manifest_*`, `test_load_corpus_*`, `test_load_scenario_*` |
| Scenario replay | `test_run_scenario_*` |
| Numeric matching | `test_numeric_match_*`, `test_tolerance_*`, `test_legitimate_zero_*` |
| Calibration aggregation | `test_check_calibration_*` |
| Malformed calibration-result robustness | `test_failed_scenarios_*`, `test_failed_ids_list_*` |
| Calibration headline | `test_calibration_headline_*` |
| Pure evaluation | `test_check_calibration_does_not_mutate_corpus` |

## Verification strategy

`tests/test_spec_018_score_calibration.py` maps one test group per EARS section. Shipped corpus
regression and CLI behavior stay in `tests/test_score_calibration.py`.

## Out of scope for this plan

Corpus content edits, objective-scoring rule changes, and trend/headline utilities.
