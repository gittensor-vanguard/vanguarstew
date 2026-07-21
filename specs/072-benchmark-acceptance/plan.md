# Plan 072 — M3/M4 acceptance gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1916

Maps the [spec](./spec.md) onto `benchmark/acceptance.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_072_acceptance.py` |
| ------------ | ------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Numeric helper | `test_is_number_semantics`, `test_is_number_rejects_oversized_int`, `test_dict_helper` |
| Partition error | `test_partition_error_non_dict_and_clean`, `test_partition_error_top_level`, `test_partition_error_per_repo_dict_row`, `test_partition_error_per_repo_string_row`, `test_partition_error_ignores_non_error_rows` |
| Composite and gap | `test_composite_masks_placeholder`, `test_recomputed_gap` |
| Gate | `test_result_carries_all_keys`, `test_accepts_a_clean_generalization_run`, `test_gap_over_bound_fails`, `test_partition_error_fails_the_gate`, `test_unscored_partition_fails_scored_and_gap`, `test_not_a_generalization_artifact_fails`, `test_non_dict_report_fails_not_raises` |
| Checks-row sanitation | `test_check_rows_list_skips_malformed_rows`, `test_check_rows_list_rejects_non_bool_passed`, `test_check_rows_list_warns_when_all_unusable` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_pass`, `test_headline_fail_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_report` |

## Verification strategy

One contract-test group per EARS section; every non-finite / placeholder / malformed-row /
gap-not-computed / non-list branch called out in the spec has an asserting test (lessons from the
Spec 057 / 059 rejections, and the finding lists on the closed Spec 068 / 069 PRs — this module is
the canonical `_partition_error`, so all three of its error locations, plus the corrupt-string-row
and non-dict cases, are pinned directly). Expectations are **literal** — e.g. a `per_repo` of
`[{"tasks": 3}, "corrupt"]` fixes `_partition_error` at `"corrupt"`, and a `0.30` gap fixes
`gap_within_bound` failing with detail `gap 0.3 exceeds max_gap 0.15` — using values whose `repr` is
stable across platforms, rather than re-deriving them from the module. Integration and CLI coverage
stay in `tests/test_acceptance.py`.
