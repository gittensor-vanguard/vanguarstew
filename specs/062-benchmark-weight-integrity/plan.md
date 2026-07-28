# Plan 062 — blend-weight integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1789

Maps the [spec](./spec.md) onto `benchmark/weight_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_062_weight_integrity.py` |
| ------------ | ------------------------------------------------- |
| Constants | `test_check_row_keys_pinned`, `test_result_carries_no_tolerance_key` |
| Numeric helper | `test_is_number_rejects_bool_numpy_and_non_finite`, `test_is_number_rejects_oversized_int`, `test_dict_helper_returns_dict_or_empty` |
| per_repo coercion | `test_per_repo_list_coerces_none_non_list_and_non_dict` |
| Scored-slice selection | `test_scored_repo_requires_positive_int_tasks`, `test_partition_scored_falls_back_to_per_repo`, `test_expand_slice_labels_scored_repos`, `test_single_repo_slice_is_run`, `test_multi_repo_slices_are_labelled`, `test_generalization_slices_are_partition_labelled` |
| Per-slice checks | `test_non_dict_weights_stops_at_weights_present`, `test_weights_present_reports_missing_component`, `test_weights_non_negative_flags_bad_components`, `test_sum_positive_short_circuits_on_invalid`, `test_zero_sum_is_not_positive`, `test_valid_weights_pass_all_three` |
| Top-level result | `test_non_dict_artifact_fails_artifact_shape`, `test_no_scored_slice_fails_artifact_shape`, `test_result_passed_is_all_checks` |
| Checks-row sanitation | `test_is_passed_accepts_bool_rejects_int`, `test_check_rows_list_skips_malformed_rows`, `test_check_rows_list_rejects_non_bool_passed`, `test_check_rows_list_warns_when_all_unusable` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_valid`, `test_headline_invalid_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; every malformed / empty / missing-component / non-list
branch called out in the spec has an asserting test (lessons from the Spec 057 / 059 rejections).
Expectations are pinned as **literal** check names, `passed` booleans and detail strings — e.g. a
slice whose `weights` is `{"judge": -1, "objective": 0.4}` fixes `weights_non_negative` failing with
detail `invalid component(s): judge=-1` — rather than re-deriving them from the module, so a silent
change in the contract is caught by these tests instead of being masked. Integration and CLI
coverage stay in `tests/test_weight_integrity.py`.
