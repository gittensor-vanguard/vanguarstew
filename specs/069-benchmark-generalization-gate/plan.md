# Plan 069 — generalization gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1954

Maps the [spec](./spec.md) onto `benchmark/generalization_gate.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_069_generalization_gate.py` |
| ------------ | ---------------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Numeric helpers | `test_is_number_accepts_finite`, `test_is_number_rejects_bool`, `test_is_number_rejects_nan`, `test_is_number_rejects_inf_and_negative_inf`, `test_is_number_rejects_str`, `test_is_number_rejects_oversized_int`, `test_num_formats_or_na`, `test_dict_helper` |
| Composite | `test_composite_masks_unscored_placeholder`, `test_composite_keeps_genuine_zero`, `test_composite_non_finite_is_none` |
| Held-out repo count | `test_scored_repos_prefers_count`, `test_scored_repos_per_repo_fallback`, `test_scored_repos_non_list_is_none` |
| Gate | `test_result_carries_all_keys`, `test_generalizes_passes_all_checks`, `test_overfit_gap_exceeds_tolerance`, `test_missing_partition_fails_has_partitions`, `test_partition_error_fails_no_partition_error`, `test_too_few_held_out_repos_fails`, `test_held_out_exceeding_tuned_is_within_tolerance` |
| Checks-row sanitation | `test_check_rows_list_warns_on_non_list_checks`, `test_check_rows_list_skips_malformed_rows`, `test_check_rows_list_rejects_non_bool_passed`, `test_check_rows_list_warns_when_all_unusable` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_generalizes`, `test_headline_overfit_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; every non-finite / placeholder / missing-partition /
error / non-list branch called out in the spec has an asserting test. Addressing the earlier close
reason on this module, `_is_number`'s edge cases (`bool`, `nan`, `inf`, `-inf`, `str`, oversized
`10 ** 400`) are each in a **dedicated** test, `_composite`'s unscored-placeholder
(`scored_repos == 0`, `composite_mean == 0.0` → `None`) and non-finite cases are pinned, `_scored_repos`'s
per_repo fallback is pinned, and the non-list-`checks` warning is asserted via `caplog`. The imported
`_partition_error` is exercised through the observable `no_partition_error` verdict (its own contract
is Spec 072), not re-specified here. Expectations are **literal** with `repr` stable across platforms
— e.g. tuned `0.70` / held-out `0.40` fixes `gap == 0.3` and `gap_within_tolerance` failing.
Integration and CLI coverage stay in `tests/test_generalization_gate.py`.
