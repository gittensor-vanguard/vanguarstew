# Plan 075 — repo-set readiness gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1939

Maps the [spec](./spec.md) onto `benchmark/repo_set_readiness.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_075_repo_set_readiness.py` |
| ------------ | --------------------------------------------------- |
| Gate evaluation and check order | `test_check_order_and_constants`, `test_check_rows_have_name_passed_detail` |
| Validity gate | `test_non_dict_config_single_failed_check_with_detail`, `test_repo_set_error_single_failed_check`, `test_valid_config_detail_and_all_checks_evaluated` |
| Adequacy thresholds | `test_min_tuned_boundary_and_detail`, `test_min_held_out_boundary_and_detail`, `test_thresholds_are_keyword_configurable` |
| Pre-LLM freeze windows | `test_before_equal_to_cutoff_passes`, `test_late_before_fails_with_sorted_names`, `test_missing_before_fails_unbounded` |
| Placeholder guard | `test_placeholder_sources_fail_with_joined_names`, `test_no_placeholders_detail` |
| Result shape | `test_result_carries_thresholds_and_counts`, `test_invalid_result_omits_repo_counts` |
| Failed checks | `test_failed_checks_non_dict_result`, `test_failed_checks_names_in_order`, `test_failed_checks_row_missing_passed_counts_failed` |
| Checks-row sanitation | `test_rows_list_none_and_empty_silent`, `test_rows_list_non_list_warned_empty`, `test_rows_list_skips_non_dict_rows_with_warning`, `test_rows_list_all_unusable_extra_warning` |
| Readiness headline | `test_headline_invalid_result_literal`, `test_headline_no_checks_literal`, `test_headline_ready_literal`, `test_headline_ready_question_mark_fallbacks`, `test_headline_not_ready_literal` |
| Pure evaluation | `test_check_readiness_no_mutation` |

## Verification strategy

One contract-test group per EARS section, mirroring the merged sibling gate specs (059–062, 071)
and the order-share spec series (038–043, 068). Expected details and headline strings are pinned
as **literal** values rather than rebuilt from the module's own formatting, so a silent wording
change is caught. Boundary cases carry the contract weight: `before == PRE_LLM_CUTOFF` (strict
`>`), threshold counts exactly at `min_tuned`/`min_held_out`, and the `?` headline fallbacks.
Fixture configs are built inline (no file I/O), keeping the tests deterministic and offline.
Integration coverage (shipped JSON sets, the CLI, #1698 load-error paths) stays in
`tests/test_repo_set_readiness.py`.
