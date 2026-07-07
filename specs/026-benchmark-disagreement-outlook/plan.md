# Plan 026 — disagreement outlook summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #874

Maps the [spec](./spec.md) onto `benchmark/disagreement_outlook.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_026_disagreement_outlook.py` |
| ------------ | ----------------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Judge telemetry selection | `test_judge_telemetry_prefers_report_over_stats`, `test_judge_telemetry_empty_when_missing` |
| Disagreement counts | `test_disagreement_counts_from_dual_and_rate`, `test_disagreement_counts_from_agree_disagree_tie`, `test_disagreement_counts_malformed_returns_none` |
| Slice summary | `test_slice_summary_computes_rate_from_counts`, `test_slice_summary_missing_counts_returns_none` |
| Partition combination | `test_combined_sums_partitions`, `test_combined_zero_dual_none_rate`, `test_combined_partial_partition_returns_none` |
| Verdict | `test_verdict_stable_at_threshold`, `test_verdict_unstable_above_threshold`, `test_verdict_none_for_non_numeric_rate` |
| Artifact-kind branches | `test_single_and_multi_kinds`, `test_generalization_partitions`, `test_generalization_partial_partition_withholds_overall`, `test_invalid_kind`, `test_custom_threshold`, `test_summary_always_includes_required_keys` |
| Disagreement outlook headline | `test_headline_exact_format`, `test_headline_generalization_exact_format`, `test_headline_unavailable_dual_order_tasks_shows_na`, `test_headline_missing_verdict_shows_unknown`, `test_headline_missing_rate_shows_na`, `test_headline_unstable_verdict`, `test_headline_nan_rate_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_disagreement_outlook.py`.
