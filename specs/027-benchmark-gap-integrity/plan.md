# Plan 027 — generalization gap integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #887

Maps the [spec](./spec.md) onto `benchmark/gap_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_027_gap_integrity.py` |
| ------------ | ---------------------------------------------- |
| Constants | `test_default_tolerance_is_zero` |
| Artifact shape | `test_non_dict_report_fails_artifact_shape`, `test_non_generalization_fails_is_generalization` |
| Generalization structure | `test_consistent_generalization_passes_all_checks`, `test_malformed_partition_types_fail_is_generalization` |
| Gap presence vs partition scoring | `test_gap_must_be_none_when_partition_unscored`, `test_gap_must_be_numeric_when_both_scored`, `test_missing_partition_composites_fail_explicit_checks` |
| Gap arithmetic | `test_expected_gap_matches_runner_semantics`, `test_wrong_gap_fails_gap_matches_partitions`, `test_tolerance_accepts_small_delta_after_rounding`, `test_legitimate_zero_gap_when_means_equal`, `test_nan_gap_fails_gap_matches_partitions`, `test_non_finite_composite_fails_gap_matches` |
| Gate result shape | `test_every_check_reported_even_when_several_fail` |
| Malformed gate-result robustness | `test_check_rows_list_treats_non_list_as_empty`, `test_check_rows_list_logs_warning_for_non_list`, `test_check_rows_list_skips_non_dict_rows`, `test_failed_checks_tolerates_malformed_result`, `test_failed_checks_logs_warning_for_skipped_rows` |
| Integrity headline | `test_integrity_headline_consistent_and_inconsistent`, `test_integrity_headline_no_checks_when_malformed` |
| Pure evaluation | `test_check_gap_integrity_does_not_mutate_report` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in `tests/test_gap_integrity.py`.
