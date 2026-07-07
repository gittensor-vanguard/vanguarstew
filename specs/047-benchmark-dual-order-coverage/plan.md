# Plan 047 — dual-order coverage summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1127

Maps the [spec](./spec.md) onto `benchmark/dual_order_coverage.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_047_dual_order_coverage.py` |
| ------------ | -------------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Ratio semantics | `test_is_ratio_rejects_bool`, `test_is_ratio_accepts_numeric` |
| Count extraction | `test_dual_order_tasks_and_task_total_happy_path`, `test_count_helpers_malformed` |
| Coverage ratio | `test_coverage_happy_path`, `test_coverage_none_branches`, `test_coverage_dual_exceeds_total` |
| Slice coverage | `test_slice_coverage_happy_path`, `test_slice_coverage_non_dict` |
| Combined coverage | `test_combined_happy_path`, `test_combined_partial_withholds` |
| Artifact-kind branches | `test_single_and_multi_kinds`, `test_generalization_partitions_and_overall`, `test_generalization_partial_partition_withholds_overall`, `test_invalid_kind_returns_none_fields`, `test_summary_always_includes_required_keys` |
| Dual-order coverage headline | `test_headline_happy_path_exact_format`, `test_headline_missing_counts_degrades`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_dual_order_coverage.py`.
