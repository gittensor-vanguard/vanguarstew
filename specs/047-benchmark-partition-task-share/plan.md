# Plan 047 — partition task share summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1133

Maps the [spec](./spec.md) onto `benchmark/partition_task_share.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_047_partition_task_share.py` |
| ------------ | ----------------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Per-repo row parsing | `test_rows_from_per_repo_none_and_non_list`, `test_rows_from_per_repo_skips_non_dict_entries` |
| Scored task counting | `test_scored_tasks_sums_positive_ints`, `test_scored_tasks_skips_invalid_tasks` |
| Partition share | `test_partition_share_valid_and_invalid`, `test_partition_entry_shape` |
| Artifact-kind branches | `test_single_kind`, `test_multi_kind_with_and_without_tasks`, `test_generalization_partitions`, `test_invalid_kind`, `test_summary_always_includes_required_keys` |
| Partition task share headline | `test_headline_generalization_exact_format`, `test_headline_multi_kind`, `test_headline_no_scored_tasks_exact`, `test_headline_nan_share_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_partition_task_share.py`.
