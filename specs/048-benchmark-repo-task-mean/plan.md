# Plan 048 — repo task mean summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1138

Maps the [spec](./spec.md) onto `benchmark/repo_task_mean.py` as-built. No product code changes.

## EARS -> test mapping

| Spec section | Test group in `test_spec_048_repo_task_mean.py` |
| ------------ | ------------------------------------------------ |
| Input coercion | `test_non_dict_artifact_returns_invalid_summary`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number task semantics | `test_is_int_rejects_bool_and_float`, `test_single_positive_integer_tasks_scores_one_repo`, `test_single_non_positive_or_non_int_tasks_score_zero` |
| `per_repo` row handling | `test_missing_per_repo_is_empty`, `test_non_list_per_repo_logs_warning`, `test_non_dict_rows_are_skipped_with_warning`, `test_only_positive_integer_tasks_count` |
| Artifact-kind branches | `test_multi_summary_uses_positive_task_rows`, `test_generalization_reports_partition_and_combined_means`, `test_invalid_kind_returns_zero_counts`, `test_summary_always_has_required_keys` |
| Headline | `test_headline_formats_mean_to_three_decimals`, `test_headline_missing_or_non_numeric_mean_uses_na`, `test_headline_non_dict_summary_is_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

Contract tests mirror the EARS clauses. Existing `tests/test_repo_task_mean.py` continues to cover
the public CLI and basic summary examples.
