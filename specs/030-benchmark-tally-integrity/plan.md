# Plan 030 — judge tally integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #901

Maps the [spec](./spec.md) onto `benchmark/tally_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_030_tally_integrity.py` |
| ------------ | ------------------------------------------------ |
| Constants | `test_valid_winner_labels_and_tally_keys` |
| Numeric semantics | `test_is_number_rejects_bool` |
| Input coercion | `test_dict_helper_returns_dict_or_empty` |
| Tally counts | `test_tally_counts_happy_path`, `test_tally_counts_rejects_malformed` |
| Row winner recount | `test_count_row_winners_ignores_unknown_labels`, `test_count_row_winners_none_when_rows_none` |
| Slice selection | `test_integrity_slices_single_run`, `test_integrity_slices_multi_repo`, `test_integrity_slices_generalization`, `test_integrity_slices_empty_when_no_scored_slice` |
| Per-slice checks | `test_consistent_single_slice_passes_all_checks`, `test_optional_rows_and_margin_checks_skipped`, `test_tally_sum_mismatch_fails`, `test_row_count_mismatch_fails`, `test_row_winners_mismatch_fails`, `test_decisive_margin_mismatch_fails` |
| Gate entrypoint | `test_non_dict_result_fails_artifact_shape`, `test_empty_dict_fails_artifact_shape`, `test_every_check_row_has_required_keys` |
| Malformed gate-result robustness | `test_check_rows_list_treats_non_list_as_empty`, `test_check_rows_list_skips_non_dict_rows`, `test_failed_checks_tolerates_malformed_result`, `test_failed_checks_logs_warning_for_skipped_rows` |
| Integrity headline | `test_integrity_headline_consistent_and_inconsistent`, `test_integrity_headline_no_checks_when_malformed`, `test_integrity_headline_uses_sanitized_row_count` |
| Pure evaluation | `test_check_tally_integrity_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_tally_integrity.py`.
