# Plan 070 — per-component floor gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1912

Maps the [spec](./spec.md) onto `benchmark/component_floor.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_070_component_floor.py` |
| ------------ | ------------------------------------------------ |
| Constants | `test_constants_are_pinned` |
| Helpers | `test_is_number_semantics`, `test_is_number_rejects_oversized_int`, `test_dict_helper`, `test_floor_check_pass_fail_and_missing`, `test_scored_metric_masks_placeholder_and_reads_nested`, `test_floor_source_generalization_vs_top_level`, `test_artifact_error_top_level_clean_and_per_repo` |
| Gate | `test_result_carries_all_keys`, `test_all_floors_pass`, `test_a_component_below_floor_fails`, `test_unscored_placeholder_fails_run_completed`, `test_non_finite_component_fails_closed`, `test_top_level_error_fails_run_completed`, `test_generalization_evaluates_tuned_partition`, `test_non_dict_result_fails_not_raises` |
| Checks-row sanitation | `test_check_rows_list_skips_non_dict_and_missing_key_rows`, `test_check_rows_list_keeps_a_dict_row_with_both_keys`, `test_check_rows_list_warns_when_all_unusable` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_pass`, `test_headline_fail_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; every non-dict / non-finite / placeholder / error /
generalization / non-list branch called out in the spec has an asserting test (lessons from the
Spec 057 / 059 rejections, and the finding list on the closed Spec 068 PR — every helper's edge
behavior, including `_floor_source` with a missing `held_out` and `_artifact_error`'s fallback, is
pinned). Expectations are **literal** — e.g. an artifact `{"composite_mean": 0.6, "composite_parts":
{"judge_mean": 0.5, "objective_mean": 0.3}}` fixes `objective_floor` failing with detail
`0.3 >= 0.4` — using decimal literals whose `repr` is stable across platforms, rather than
re-deriving them from the module. Integration and CLI coverage stay in
`tests/test_component_floor.py`.
