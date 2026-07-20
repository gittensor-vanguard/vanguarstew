# Plan 061 — objective anchor integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1739

Maps the [spec](./spec.md) onto `benchmark/objective_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_061_objective_integrity.py` |
| ------------ | ---------------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Numeric helpers | `test_is_number_semantics`, `test_is_number_rejects_oversized_int`, `test_is_ratio_bounds`, `test_dict_helper_returns_dict_or_empty`, `test_round3_and_mean` |
| Row / per_repo coercion | `test_rows_list_coerces_none_non_list_and_non_dict_rows`, `test_per_repo_list_coercion` |
| Slice selection | `test_single_repo_rows_slice_is_unprefixed`, `test_multi_repo_slices_are_labelled`, `test_generalization_slices_are_partition_labelled`, `test_no_scored_slice_reports_artifact_shape` |
| Per-slice checks | `test_rows_present_and_objectives_present`, `test_recall_fields_valid_flags_bool_and_out_of_range`, `test_recall_absent_keys_are_ignored`, `test_kind_recall_only_when_actual_kinds`, `test_objective_mean_matches_rows_within_tolerance`, `test_objective_mean_unavailable_fails_closed` |
| Detail truncation | `test_recall_detail_truncates_after_three_with_ellipsis`, `test_kind_recall_detail_truncates_after_three_without_ellipsis` |
| per_repo well-formedness | `test_malformed_per_repo_string_rows_flagged`, `test_per_repo_dict_error_row_not_flagged`, `test_no_per_repo_container_omits_wellformed_check` |
| Top-level result | `test_non_dict_artifact_fails_artifact_shape`, `test_result_always_carries_passed_checks_tolerance`, `test_tolerance_echoes_caller` |
| Checks-row sanitation | `test_check_rows_list_skips_malformed_rows`, `test_check_rows_list_rejects_non_bool_passed` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_valid`, `test_headline_invalid_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; every malformed / empty / missing-key / truncation
branch called out in the spec has an asserting test (lessons from the Spec 057 / 059
rejections). Anchor expectations are pinned as **literal** values (e.g. a row objective of
`{"module_recall": 0.5}` fixes `objective_mean` at `0.5`) rather than re-derived by calling
`score.objective_component` inside the test, so a silent change in the anchor is caught by these
contract tests instead of being masked. Integration and CLI coverage stay in
`tests/test_objective_integrity.py`.

## Recorded discrepancy (no code change)

The module docstring's "inflate ... via `float(True) == 1.0` (#1233)" motivation is stale: the
as-built `score._recall_for_component` floors a bool recall to `0.0`. The spec records this and
documents the as-built deflation behavior; correcting the docstring is deliberately out of scope
so this spec stays a documentation-only change.
