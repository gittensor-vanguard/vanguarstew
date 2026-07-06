# Plan 031 — sample adequacy gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #911

Maps the [spec](./spec.md) onto `benchmark/sample_adequacy.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_031_sample_adequacy.py` |
| ------------ | ---------------------------------------------- |
| Constants | `test_default_min_tasks_is_three` |
| Numeric semantics | `test_bool_is_not_numeric_for_tasks` |
| Input coercion | `test_non_dict_result_coerced_to_empty_dict` |
| Task total | `test_single_repo_numeric_tasks`, `test_multi_repo_sums_per_repo`, `test_generalization_sums_partitions`, `test_malformed_per_repo_yields_none_total` |
| Tally accounting | `test_missing_tally_decided_is_none`, `test_incomplete_tally_decided_is_none`, `test_complete_tally_decided_is_sum` |
| Gate checks | `test_adequate_run_passes_all_checks`, `test_too_few_tasks_fails_enough_tasks`, `test_tally_mismatch_fails_all_tasks_decided`, `test_errored_run_fails_run_scored` |
| Gate result shape | `test_gate_returns_expected_keys` |
| Malformed gate-result robustness | `test_check_rows_list_treats_non_list_as_empty`, `test_check_rows_list_none_and_empty_silent`, `test_check_rows_list_skips_non_dict_rows`, `test_check_rows_list_warns_when_all_unusable`, `test_failed_checks_tolerates_malformed_result` |
| Sample adequacy headline | `test_headline_adequate_and_inadequate`, `test_headline_tasks_shows_na_when_non_numeric`, `test_headline_no_checks_when_malformed`, `test_headline_no_checks_when_passed_false_and_zero_sanitized`, `test_headline_no_checks_when_passed_true_and_zero_sanitized` |
| Pure evaluation | `test_check_sample_adequacy_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_sample_adequacy.py`.
