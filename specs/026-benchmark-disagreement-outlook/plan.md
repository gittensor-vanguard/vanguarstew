# Plan 026 — pairwise judge disagreement outlook

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #874

Maps the [spec](./spec.md) onto `benchmark/disagreement_outlook.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_026_disagreement_outlook.py` |
| ------------ | ----------------------------------------------------- |
| Input coercion & number validity | `test_dict_helper_returns_dict_or_empty`, `test_is_int_semantics`, `test_is_number_semantics` |
| Disagreement counts (`_disagreement_counts`) | `test_counts_from_dual_and_disagree`, `test_counts_derive_dual_from_agree_disagree_tie`, `test_counts_derive_disagreements_from_rate`, `test_counts_reject_invalid_or_negative` |
| Slice summary (`_slice_summary`) | `test_slice_prefers_stats_over_stale_report`, `test_slice_falls_back_to_report_when_stats_absent_or_empty`, `test_slice_empty_when_no_usable_source`, `test_slice_non_dict_coerced` |
| Overall summary — shape & kinds | `test_result_always_includes_required_keys`, `test_single_and_multi_top_level_slice`, `test_non_dict_and_empty_artifact_are_invalid`, `test_missing_telemetry_yields_none_fields` |
| Overall summary — stats over stale report | `test_summary_recomputes_stale_report_rate_from_stats` |
| Overall summary — verdict & threshold | `test_verdict_stable_unstable_and_boundary`, `test_custom_and_non_number_threshold_coercion`, `test_non_finite_rate_yields_none_verdict` |
| Combined outlook (`_combined`) | `test_generalization_combined_sums_partitions`, `test_generalization_missing_partition_yields_none_overall`, `test_combined_helper_zero_dual_branch`, `test_combined_helper_incomplete_is_empty`, `test_generalization_zero_dual_partitions_yield_none` |
| Verdict (`_verdict`) | `test_verdict_helper_direct` |
| Headline (`disagreement_outlook_headline`) | `test_headline_single_line`, `test_headline_generalization_appends_partition_rates`, `test_headline_non_numeric_rate_and_non_dict` |
| Pure evaluation | `test_summary_does_not_mutate_input_for_every_shape`, `test_summary_performs_no_io` |

## Result-field semantics pinned (avoid ambiguity)

| Field / behavior | Rule | Test |
| ---------------- | ---- | ---- |
| source preference | `judge_order_stats` wins over `judge_report`; a stale report rate never overrides authoritative stats counts | `test_slice_prefers_stats_over_stale_report`, `test_summary_recomputes_stale_report_rate_from_stats` |
| `disagreements` from rate only | `round(disagreement_rate * dual)` when neither `disagree` nor `disagreements` is present | `test_counts_derive_disagreements_from_rate` |
| `verdict` boundary | `rate <= threshold` is **stable** (inclusive); non-finite rate → `None` | `test_verdict_stable_unstable_and_boundary`, `test_verdict_helper_direct` |
| `stable_threshold` echo | coerced `float`, or `DEFAULT_STABLE_THRESHOLD` (0.3) for a non-finite/non-number argument | `test_custom_and_non_number_threshold_coercion` |
| generalization top-level | the **combined** (summed) outlook; per-partition detail under `partitions` | `test_generalization_combined_sums_partitions` |
| zero dual-order tasks | a zero-dual partition yields an empty slice → all-`None` overall (not the `_combined` 0 branch, which is reachable only via the helper directly) | `test_generalization_zero_dual_partitions_yield_none`, `test_combined_helper_zero_dual_branch` |

## Verification strategy

One contract-test group per EARS section; every assertion is pinned against the live output of the
as-built module. The `_combined` zero-`dual` branch, unreachable through `summarize` because a
zero-`dual` slice carries no derivable rate, is pinned by calling the helper directly. Integration
and CLI tests stay in `tests/test_disagreement_outlook.py`.
