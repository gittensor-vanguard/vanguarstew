# Plan 015 — acceptance gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #764

Maps the [spec](./spec.md) onto `benchmark/acceptance.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_015_acceptance.py` |
| ------------ | ------------------------------------------- |
| Input coercion | `test_dict_helper_returns_dict_or_empty`, `test_is_number_rejects_bools_and_non_numbers` |
| Partition errors | `test_partition_error_reads_top_level_first`, `test_partition_error_reads_per_repo_rows_in_order`, `test_partition_error_treats_string_rows_as_errors`, `test_partition_error_ignores_unusable_shapes` |
| Acceptance gate | `test_clean_report_passes_all_five_checks`, `test_checks_are_always_reported_in_order`, `test_non_dict_report_fails_without_raising`, `test_per_repo_error_fails_no_partition_error_detail_exact`, `test_scored_repos_threshold_is_configurable`, `test_gap_boundary_is_inclusive`, `test_uncomputed_gap_fails_gap_checks`, `test_result_gap_is_none_unless_numeric` |
| Failed checks | `test_failed_checks_helper_on_malformed_containers`, `test_failed_checks_skips_unusable_rows_with_warning`, `test_failed_checks_names_failing_checks` |
| Acceptance headline | `test_headline_no_checks_exact`, `test_headline_pass_exact`, `test_headline_fail_exact` |
| Pure evaluation | `test_check_does_not_mutate_report` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_acceptance.py`.
