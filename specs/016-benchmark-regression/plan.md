# Plan 016 — candidate-vs-baseline regression gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #765

Maps the [spec](./spec.md) onto `benchmark/regression.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_016_regression.py` |
| ------------ | ------------------------------------------- |
| Input coercion | `test_non_dict_artifacts_coerced_and_fail_gracefully`, `test_dict_helper_returns_dict_or_empty` |
| Numeric semantics | `test_is_number_accepts_int_and_float`, `test_is_number_rejects_bool`, `test_is_number_rejects_non_numbers` |
| Rounding and `None` propagation | `test_round_rounds_numbers_to_three_places`, `test_round_returns_none_for_non_number`, `test_none_propagates_from_absent_composite`, `test_none_propagates_from_absent_disagreement` |
| Compared composite | `test_composites_come_from_headline_score`, `test_unscored_or_errored_artifact_has_none_composite` |
| Order-disagreement resolution | `test_flat_disagreement_prefers_stats_over_report`, `test_flat_disagreement_none_without_telemetry`, `test_partition_counts_prefer_stats_and_derive_dual`, `test_partition_counts_accept_disagreements_alias`, `test_partition_counts_none_when_dual_missing_or_zero`, `test_conflicting_sources_stats_wins`, `test_negative_dual_order_tasks_yields_no_count_rate`, `test_generalization_sums_both_partitions`, `test_generalization_none_when_no_partition_counts`, `test_flat_used_without_both_partitions` |
| Gate evaluation | `test_checks_order_and_shape`, `test_both_scored_gate`, `test_no_composite_regression_inclusive_bound`, `test_no_judge_instability_increase_gate`, `test_judge_check_passes_vacuously_without_both_rates`, `test_both_composites_none_fails_gracefully`, `test_passed_is_conjunction_of_checks`, `test_result_always_includes_required_keys`, `test_default_thresholds`, `test_thresholds_are_configurable` |
| Checks-row sanitization | `test_check_rows_list_none_and_empty_are_silent`, `test_check_rows_list_non_list_warns_and_empties`, `test_check_rows_list_skips_unusable_rows`, `test_check_rows_list_all_unusable_warns` |
| Failed checks | `test_failed_checks_names_failed_rows`, `test_failed_checks_empty_when_all_pass`, `test_failed_checks_robust_to_malformed_checks` |
| Regression headline | `test_headline_ok_exact_format`, `test_headline_blocked_exact_format`, `test_headline_no_checks_evaluated`, `test_headline_non_list_checks_shows_no_checks` |
| Pure evaluation | `test_check_does_not_mutate_inputs`, `test_check_regression_performs_no_io` |

## Reviewer findings → closure

| Finding (PR #1290, closed) | Spec section | Test(s) |
| -------------------------- | ------------ | ------- |
| 1a — conflicting disagreement sources undefined | *Order-disagreement resolution → Conflicting disagreement sources* | `test_conflicting_sources_stats_wins` |
| 1b — zero/negative `dual_order_tasks` undefined | *Order-disagreement resolution → Zero or negative `dual_order_tasks`* | `test_partition_counts_none_when_dual_missing_or_zero`, `test_negative_dual_order_tasks_yields_no_count_rate` |
| 1c — `None` propagation from rounding undefined | *Rounding and `None` propagation* | `test_round_returns_none_for_non_number`, `test_none_propagates_from_absent_composite`, `test_none_propagates_from_absent_disagreement` |
| 2 — purity test incomplete (no-I/O + deep mutation) | *Pure evaluation* | `test_check_regression_performs_no_io`, `test_check_does_not_mutate_inputs` (deep-copy incl. nested generalization) |
| 3a — missing empty-`failed_checks` test | *Failed checks* | `test_failed_checks_empty_when_all_pass` |
| 3b — missing both-composites-`None` gate test | *Gate evaluation → Both composites absent* | `test_both_composites_none_fails_gracefully` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_regression.py`.
