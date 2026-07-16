# Plan 014 — challenger promotion gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #763

Maps the [spec](./spec.md) onto `benchmark/promotion.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_014_promotion.py` |
| ------------ | ------------------------------------------- |
| Input coercion | `test_non_dict_result_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Numeric semantics | `test_is_number_accepts_int_and_float`, `test_is_number_rejects_bool`, `test_is_number_rejects_non_numbers` |
| Evaluated partition | `test_generalization_evaluated_on_tuned_partition`, `test_top_level_used_when_not_both_partitions`, `test_top_level_or_partition_error_marks_incomplete` |
| Scored composite | `test_non_numeric_composite_is_none`, `test_unscored_placeholder_is_none`, `test_genuine_zero_kept_when_scored`, `test_single_repo_zero_kept`, `test_bool_scored_repos_not_placeholder` |
| Decisive margin | `test_margin_prefers_explicit_field`, `test_margin_from_tally`, `test_margin_from_judge_report`, `test_margin_none_when_no_source`, `test_margin_precedence` |
| Gate evaluation | `test_checks_order_and_shape`, `test_run_completed_gate`, `test_composite_floor_gate`, `test_beats_baseline_gate`, `test_judge_trustworthy_single_order_passes`, `test_judge_trustworthy_high_disagreement_fails`, `test_judge_trustworthy_non_numeric_fails`, `test_result_always_includes_required_keys`, `test_bounds_are_inclusive`, `test_default_thresholds`, `test_thresholds_are_configurable` |
| Checks-row sanitization | `test_check_rows_list_none_and_empty_are_silent`, `test_check_rows_list_non_list_warns_and_empties`, `test_check_rows_list_skips_unusable_rows`, `test_check_rows_list_all_unusable_warns` |
| Failed checks | `test_failed_checks_names_failed_rows`, `test_failed_checks_robust_to_malformed_checks` |
| Promotion headline | `test_headline_promote_exact_format`, `test_headline_hold_exact_format`, `test_headline_no_checks_evaluated`, `test_headline_non_list_checks_shows_no_checks` |
| Pure evaluation | `test_check_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_promotion.py`.
