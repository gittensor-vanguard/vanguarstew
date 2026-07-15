# Plan 059 — composite score integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1690

Maps the [spec](./spec.md) onto `benchmark/score_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_059_score_integrity.py` |
| ------------ | ------------------------------------------------ |
| Constants | `test_default_constants` |
| Numeric semantics | `test_is_number_rejects_bool_and_non_finite`, `test_round3_happy_path_and_invalid` |
| Input coercion | `test_dict_helper_returns_dict_or_empty` |
| Weight resolution | `test_weights_top_level`, `test_weights_from_per_repo`, `test_weights_default_fallback` |
| Expected blend | `test_expected_composite_normalized_blend`, `test_expected_composite_zero_weights` |
| Scoring slices | `test_scoring_slices_run_and_generalization`, `test_partition_scored_semantics`, `test_scoring_slices_empty_when_unscored` |
| Per-slice checks | `test_consistent_slice_passes_all_checks`, `test_blend_mismatch_fails`, `test_missing_parts_fails`, `test_out_of_range_fails` |
| Gate entrypoint | `test_non_dict_fails_artifact_shape`, `test_unscored_generalization_fails_artifact_shape`, `test_tolerance_is_overridable`, `test_every_check_row_has_required_keys` |
| Malformed gate-result robustness | `test_check_rows_list_treats_non_list_as_empty`, `test_failed_checks_tolerates_malformed_result` |
| Integrity headline | `test_headline_consistent_exact`, `test_headline_inconsistent_exact`, `test_headline_no_checks_exact` |
| Pure evaluation | `test_check_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_score_integrity.py`.
