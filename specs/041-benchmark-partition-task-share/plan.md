# Plan 041 — partition task share summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1095

Maps the [spec](./spec.md) onto `benchmark/partition_task_share.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_041_partition_task_share.py` |
| ------------ | ----------------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty`, `test_extra_artifact_keys_ignored` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers`, `test_is_int_rejects_numpy_integer_scalars` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Per-repo row parsing | `test_rows_from_per_repo_none_is_empty`, `test_rows_from_per_repo_non_list_warns`, `test_rows_from_per_repo_skips_non_dict_entries` |
| Scored-task counting | `test_scored_tasks_sums_positive_ints_only`, `test_scored_tasks_skips_negative_and_missing`, `test_scored_tasks_rejects_bool_tasks` |
| Partition share | `test_partition_share_happy_path`, `test_partition_share_zero_tasks_is_zero_not_none`, `test_partition_share_invalid_total_is_none`, `test_partition_entry_shape` |
| Artifact-kind branches | `test_single_kind_counts_top_level_tasks`, `test_single_zero_or_missing_tasks`, `test_multi_kind_aggregates_and_partitions`, `test_multi_zero_tasks_partitions_none`, `test_generalization_partitions_and_shares`, `test_generalization_empty_partition_share_zero`, `test_generalization_zero_total_share_none`, `test_invalid_kind_returns_zeroed_summary`, `test_summary_always_includes_required_keys` |
| Partition task share headline | `test_headline_no_scored_tasks_exact`, `test_headline_generalization_exact_format`, `test_headline_multi_exact_format`, `test_headline_none_share_shows_na`, `test_headline_nan_share_shows_na`, `test_headline_non_dict_summary_coerced`, `test_headline_unknown_kind_fallback` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_partition_task_share.py`.
