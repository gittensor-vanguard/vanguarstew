# Plan 067 — multi-repo coverage gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1898

Maps the [spec](./spec.md) onto `benchmark/coverage.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_067_coverage.py` |
| ------------ | ----------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Helpers | `test_is_number_semantics`, `test_is_number_rejects_oversized_int`, `test_dict_helper`, `test_per_repo_list_coercion`, `test_repo_tasks` |
| Per-repo collection | `test_collect_multi`, `test_collect_generalization`, `test_collect_none` |
| Counting | `test_partition_counts_dicts_and_corrupt_strings`, `test_total_scored_tasks` |
| Gate | `test_result_carries_all_keys`, `test_sufficient_multi_repo_passes`, `test_min_repos_and_skipped_and_tasks_fail`, `test_single_repo_forces_breadth_checks_false` |
| Checks-row sanitation | `test_check_rows_list_skips_malformed_rows`, `test_check_rows_list_rejects_non_bool_passed`, `test_check_rows_list_warns_when_all_unusable` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_sufficient`, `test_headline_insufficient_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; every malformed / single-repo / corrupt-row / non-list
branch called out in the spec has an asserting test (lessons from the Spec 057 / 059 rejections).
Expectations are pinned as **literal** check names, `passed` booleans and detail strings — e.g. a
`per_repo` of `[{"tasks": 3}, {"tasks": 0}, "corrupt"]` fixes `repos_total == 3`, `repos_scored ==
1`, `repos_skipped == 2` — rather than re-deriving them from the module, so a silent contract change
is caught here instead of masked. Integration and CLI coverage stay in `tests/test_coverage.py`.
