# Plan 029 — per-task row integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #900

Maps the [spec](./spec.md) onto `benchmark/row_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_029_row_integrity.py` |
| ------------ | ------------------------------------------------ |
| Constants | `test_default_tolerance_and_weight_constants` |
| Finite numeric semantics | `test_is_number_rejects_bool`, `test_non_numeric_composite_fails_comparison` |
| Artifact shape | `test_non_dict_artifact_fails_artifact_shape`, `test_empty_dict_fails_artifact_shape` |
| Slice selection | `test_single_repo_run_slice`, `test_multi_repo_checks_scored_entries`, `test_generalization_checks_scored_partitions`, `test_generalization_skips_unscored_partitions` |
| Weight resolution | `test_custom_weights_are_respected`, `test_default_weights_apply_when_missing` |
| Per-slice checks | `test_consistent_single_repo_passes`, `test_row_composite_mismatch_fails`, `test_composite_mean_mismatch_fails`, `test_judge_mean_mismatch_fails`, `test_objective_mean_mismatch_fails`, `test_tolerance_is_configurable` |
| Row and container robustness | `test_malformed_rows_skipped_with_warning`, `test_malformed_per_repo_entry_skipped` |
| Gate result shape | `test_gate_returns_passed_checks_tolerance` |
| Malformed gate-result robustness | `test_check_rows_list_treats_non_list_as_empty`, `test_check_rows_list_logs_warning_for_non_list`, `test_check_rows_list_skips_rows_missing_keys`, `test_failed_checks_tolerates_malformed_result` |
| Integrity headline | `test_integrity_headline_consistent_and_inconsistent`, `test_integrity_headline_no_checks_when_malformed`, `test_integrity_headline_uses_sanitized_count` |
| Pure evaluation | `test_check_row_integrity_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in `tests/test_row_integrity.py`.
