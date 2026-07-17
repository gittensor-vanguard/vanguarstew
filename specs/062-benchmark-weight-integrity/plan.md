# Plan 062 — blend weight integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1789

Maps the [spec](./spec.md) onto `benchmark/weight_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_062_weight_integrity.py` |
| ------------ | ------------------------------------------------- |
| Constants | `test_constants_are_pinned`, `test_result_has_no_tolerance_key` |
| Numeric helper (`_is_number`) | `test_is_number_accepts_only_exact_finite_int_float`, `test_is_number_rejects_bool_and_numpy_scalars`, `test_is_number_rejects_non_finite`, `test_is_number_rejects_oversized_int` |
| Dict / per_repo coercion | `test_dict_helper_returns_dict_or_empty`, `test_per_repo_list_none_and_empty_are_silent`, `test_per_repo_list_warns_on_non_list_and_skips_non_dict_rows` |
| Scored-slice predicates | `test_scored_repo_requires_positive_numeric_tasks`, `test_partition_scored_prefers_per_repo_then_scored_repos_then_tasks` |
| Slice selection | `test_single_repo_slice_is_unprefixed_run`, `test_multi_repo_slices_skip_unscored_rows`, `test_generalization_slices_are_partition_labelled`, `test_empty_per_repo_yields_no_slices_and_artifact_shape` |
| Per-slice checks | `test_non_dict_weights_early_returns_single_check`, `test_weights_present_reports_missing_component`, `test_weights_non_negative_flags_negative_and_invalid`, `test_invalid_component_early_returns_sum_check`, `test_weights_sum_positive_zero_and_positive` |
| Top-level result | `test_non_dict_artifact_fails_artifact_shape`, `test_result_always_carries_passed_and_checks` |
| Check-row sanitation | `test_is_passed_accepts_bool_rejects_int`, `test_check_row_field_semantics`, `test_check_rows_list_none_and_empty_silent`, `test_check_rows_list_skips_malformed_rows` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_valid`, `test_headline_invalid_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; every malformed / empty / early-return / warning branch
called out in the spec has an asserting test (lessons from the Spec 057 / 059 rejections).
Expected details are pinned as **literal** strings (e.g. `"judge + objective = 1.0 (positive)"`)
rather than rebuilt from the module's own formatting, so a silent wording or threshold change is
caught by these contract tests instead of being masked.

The `_is_number` (rejects numpy scalars) vs `_is_passed` (accepts numpy bools) asymmetry is
asserted directly, since it is the module's most surprising deliberate choice. numpy is not a
test dependency, so the numpy-scalar cases are covered with a stand-in whose `type(...).__name__`
matches (`bool_`), exercising the same branch without importing numpy. Integration and CLI
coverage stay in `tests/test_weight_integrity.py`.
