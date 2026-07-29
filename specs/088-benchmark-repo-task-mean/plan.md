# Plan 046 — repo task mean summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1132

Maps the [spec](./spec.md) onto `benchmark/repo_task_mean.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_046_repo_task_mean.py` |
| ------------ | ------------------------------------------------ |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| per_repo row extraction | `test_rows_from_per_repo_none_and_non_list`, `test_rows_from_per_repo_skips_non_dict_rows`, `test_rows_from_per_repo_warns_on_non_list` |
| Partition stats | `test_partition_stats_counts_only_positive_int_tasks`, `test_partition_stats_empty_yields_none_mean` |
| Artifact-kind branches | `test_single_artifact`, `test_single_without_positive_tasks`, `test_multi_artifact`, `test_generalization_partitions_and_overall`, `test_invalid_kind_returns_zeroed_fields`, `test_summary_always_includes_required_keys` |
| Repo task mean headline | `test_headline_exact_format`, `test_headline_none_mean_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_repo_task_mean.py`. The contract tests assert the as-built module already satisfies
every criterion — a failure marks a spec/behavior drift, not a feature request.
