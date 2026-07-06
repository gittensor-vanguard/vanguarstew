# Plan 030 — judge tally integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #901

Maps the [spec](./spec.md) onto `benchmark/tally_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_030_tally_integrity.py` |
| ------------ | ------------------------------------------------ |
| Winner vocabulary | `test_valid_winners_constant`, `test_count_row_winners_ignores_unknown_labels` |
| Finite numeric semantics | `test_is_number_rejects_bool`, `test_tally_counts_rejects_non_numeric` |
| Artifact shape | `test_non_dict_artifact_fails_artifact_shape`, `test_empty_dict_fails_artifact_shape`, `test_zero_tasks_not_selected` |
| Slice selection | `test_single_repo_run_slice`, `test_multi_repo_checks_scored_entries`, `test_generalization_checks_scored_partitions`, `test_generalization_skips_unscored_partitions` |
| Per-slice checks | `test_consistent_single_repo_passes`, `test_tally_sum_mismatch_fails`, `test_rows_match_tasks_when_rows_present`, `test_row_winners_mismatch_fails`, `test_decisive_margin_matches_when_present`, `test_slice_without_rows_skips_row_checks`, `test_slice_without_margin_skips_margin_check` |
| Tally and container robustness | `test_malformed_rows_skipped_with_warning`, `test_malformed_per_repo_entry_skipped` |
| Gate result shape | `test_gate_returns_passed_and_checks` |
| Malformed gate-result robustness | `test_check_rows_list_treats_non_list_as_empty`, `test_check_rows_list_logs_warning_for_non_list`, `test_failed_checks_tolerates_malformed_result` |
| Integrity headline | `test_integrity_headline_consistent_and_inconsistent`, `test_integrity_headline_no_checks_when_malformed`, `test_integrity_headline_uses_sanitized_count` |
| Pure evaluation | `test_check_tally_integrity_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in `tests/test_tally_integrity.py`.
