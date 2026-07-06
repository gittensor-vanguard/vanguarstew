# Plan 017 — offline pairwise-judge calibration harness

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #794

How the [spec](./spec.md) maps onto `benchmark/judge_calibration.py` as-built. No new product
code; this records the contract surface so future calibration changes are reviewed against a plan.

## Architecture / control flow

```
validate_scenario(data) → list[str] errors

load_manifest(path) → dict
load_scenario(path) → dict (raises on validation errors)
load_corpus(root) → list[dict] (manifest + file consistency checks)

run_scenario(scenario, llm)
  └─ pairwise_judge + judge_verbose → {passed, actual_winner, ...}

check_symmetry(scenario, llm)  [when expect_symmetric]
  └─ forward vs swapped pairwise_judge → {passed, forward, backward}

check_calibration(corpus, llm)
  ├─ run_scenario for each scenario
  ├─ check_symmetry when flagged
  └─ aggregate passed / failed ids

failed_scenarios(result) → list[str]  (robust to malformed failed list)
calibration_headline(result) → str     (robust to malformed fields)
```

## Data model

### Required scenario keys

| Key | Type | Role |
| --- | ---- | ---- |
| `id` | non-empty `str` | stable scenario identifier |
| `description` | any JSON | human label |
| `context` | JSON value | frozen context passed to judge |
| `revealed` | JSON value | reference trajectory |
| `submission_a` / `submission_b` | JSON value | challenger/baseline payloads |
| `expected_winner` | `A` \| `B` \| `tie` | golden ranking |

Optional: `expect_symmetric` (bool), `tags` (list).

### Calibration result shape

| Key | Type | Role |
| --- | ---- | ---- |
| `passed` | `bool` | all winner + symmetry checks passed |
| `scenario_count` | `int` | number of scenarios run |
| `results` | `list[dict]` | per-scenario rows from `run_scenario` |
| `symmetry_checks` | `list[dict]` | optional symmetry rows |
| `failed` | `list[str]` | ids that failed any check |

## EARS → test mapping

| Spec section | Test group in `test_spec_017_judge_calibration.py` |
| ------------ | --------------------------------------------------- |
| Scenario validation | `test_validate_scenario_*` |
| Manifest and corpus loading | `test_load_manifest_*`, `test_load_corpus_*`, `test_load_scenario_*` |
| Scenario replay | `test_run_scenario_*` |
| Symmetry check | `test_check_symmetry_*` |
| Calibration aggregation | `test_check_calibration_*` |
| Malformed calibration-result robustness | `test_failed_scenarios_*`, `test_failed_ids_list_*`, `test_symmetry_checks_list_*` |
| Calibration headline | `test_calibration_headline_*` |
| Pure evaluation | `test_check_calibration_does_not_mutate_corpus` |

## Verification strategy

`tests/test_spec_017_judge_calibration.py` maps one test group per EARS section. Shipped corpus
regression and CLI behavior stay in `tests/test_judge_calibration.py`.

## Out of scope for this plan

Corpus content edits, judge ranking rule changes, and online LLM calibration.
