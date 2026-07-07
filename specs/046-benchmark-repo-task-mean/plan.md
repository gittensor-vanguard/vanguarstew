# Plan 046 — repo task mean summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1132

Maps the [spec](./spec.md) onto `benchmark/repo_task_mean.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_046_repo_task_mean.py` |
| ------------ | ---------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Per-repo row parsing | `test_rows_from_per_repo_none_is_empty`, `test_rows_from_per_repo_non_list_warns`, `test_rows_from_per_repo_skips_non_dict_entries` |
| Partition stats | `test_partition_stats_happy_path`, `test_partition_stats_zero_scored_mean_none`, `test_partition_stats_skips_non_positive_tasks` |
| Artifact-kind branches | `test_single_kind_positive_and_zero_tasks`, `test_multi_kind_aggregates`, `test_generalization_partitions_and_overall`, `test_invalid_kind_returns_zeroed_summary`, `test_summary_always_includes_required_keys` |
| Repo task mean headline | `test_headline_happy_path_exact_format`, `test_headline_none_mean_shows_na`, `test_headline_nan_mean_formats_as_nan`, `test_headline_unknown_kind_fallback`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_repo_task_mean.py`.
