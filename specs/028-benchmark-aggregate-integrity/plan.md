# Plan 028 — multi-repo aggregate integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #888

Maps the [spec](./spec.md) onto `benchmark/aggregate_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_028_aggregate_integrity.py` |
| ------------ | ------------------------------------------------------ |
| Constants | `test_default_tolerance_is_zero` |
| Finite numeric semantics | `test_is_finite_number_rejects_bool_nan_inf`, `test_is_finite_number_rejects_numpy_when_available` |
| Artifact shape | `test_non_dict_artifact_fails_artifact_shape`, `test_single_repo_fails_artifact_shape`, `test_generalization_without_per_repo_fails` |
| Slice selection | `test_generalization_checks_each_partition`, `test_aggregate_slices_requires_per_repo_list` |
| Per-slice checks | `test_consistent_multi_repo_passes`, `test_inflated_composite_mean_fails`, `test_scored_repos_mismatch_fails`, `test_skipped_mismatch_fails`, `test_missing_scored_composite_fails`, `test_judge_mean_mismatch_fails`, `test_zero_scored_repos_headline_is_zero` |
| Per-repo container robustness | `test_malformed_per_repo_container_fails_artifact_shape`, `test_malformed_per_repo_row_skipped_with_warning` |
| Gate result shape | `test_gate_returns_passed_checks_tolerance` |
| Malformed gate-result robustness | `test_check_rows_list_treats_non_list_as_empty`, `test_check_rows_list_logs_warning_for_non_list`, `test_check_rows_list_skips_malformed_rows`, `test_failed_checks_tolerates_malformed_result` |
| Integrity headline | `test_integrity_headline_consistent_and_inconsistent`, `test_integrity_headline_no_checks_when_malformed` |
| Pure evaluation | `test_check_aggregate_integrity_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in `tests/test_aggregate_integrity.py`.
