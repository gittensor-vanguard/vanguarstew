# Plan 063 — judge report integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1865

Maps the [spec](./spec.md) onto `benchmark/judge_report_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_063_judge_report_integrity.py` |
| ------------ | ------------------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Numeric helper | `test_is_number_accepts_finite_int_float`, `test_is_number_rejects_bool_non_finite_oversized`, `test_is_number_rejects_decimal_and_other_numeric_types` |
| Verdict helper | `test_is_passed_bool_and_numpy_typenames`, `test_is_passed_rejects_int_and_bool_subclass` |
| Dict / per_repo coercion | `test_dict_helper`, `test_per_repo_list_none_and_empty_silent`, `test_per_repo_list_warns_on_non_list`, `test_per_repo_list_drops_non_dict_without_per_entry_warning` |
| Check-row field & sanitation | `test_check_row_field_semantics`, `test_check_rows_list_none_and_empty_silent`, `test_check_rows_list_warns_on_non_list`, `test_check_rows_list_skips_and_warns_on_malformed_rows`, `test_check_rows_list_warns_when_no_usable_rows` |
| Tally & stats helpers | `test_tally_counts_requires_all_keys_numeric`, `test_stats_dual_order_tasks_field_then_sum`, `test_expected_disagreement_rate` |
| Slice detection | `test_slice_has_judge_telemetry_branches`, `test_expand_slice_per_repo_first`, `test_generalization_and_multi_and_run_slices`, `test_no_telemetry_yields_no_slices` |
| Per-slice checks | `test_report_and_stats_present`, `test_tally_matches_and_no_tally_branch`, `test_dual_disagreements_and_rate_match`, `test_rate_na_branch`, `test_missing_stats_fails_the_three_comparisons` |
| per_repo well-formedness | `test_malformed_per_repo_string_rows_flagged`, `test_dict_error_row_and_blanks_not_flagged`, `test_no_per_repo_container_omits_check` |
| Top-level result | `test_non_dict_artifact_fails_artifact_shape`, `test_result_always_carries_passed_and_checks` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_consistent`, `test_headline_inconsistent_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; every malformed / empty / early-return / **warning**
branch called out in the spec has an asserting test (lessons from the Spec 057/059/061/062
rejections, which faulted specifically: undefined numeric types like `Decimal`, untested
warning-emission branches, narrow numpy coverage, and unverified `int`-vs-`bool` rejection — all
covered here explicitly).

Expected details/names are pinned as **literal** strings rather than rebuilt from the module's own
formatting, so a silent wording change is caught. numpy is not a test dependency: the numpy-bool
typename cases are exercised with stand-ins whose `type(...).__name__` is asserted to be `bool_`
(and `bool8` / `bool`) so they provably hit the module's `_NUMPY_BOOL_TYPENAMES` branch. Warning
emission is asserted with `caplog` on the `benchmark.judge_report_integrity` logger for each warn
branch. Integration and CLI coverage stay in `tests/test_judge_report_integrity.py`.
