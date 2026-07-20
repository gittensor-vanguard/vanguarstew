# Plan 064 — repeatability gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1879

Maps the [spec](./spec.md) onto `benchmark/repeatability_gate.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_064_repeatability_gate.py` |
| ------------ | ---------------------------------------------------- |
| Constants | `test_constants_and_defaults`, `test_effective_min_runs_floor` |
| Helpers | `test_is_number_accepts_int_float_rejects_bool`, `test_is_number_has_no_finiteness_or_overflow_guard`, `test_is_number_rejects_decimal_and_non_numerics`, `test_dict_helper` |
| Result shape | `test_result_carries_checks_and_spread_metrics`, `test_check_order_is_stable`, `test_passed_is_all_checks` |
| `artifacts_is_list` | `test_artifacts_is_list_passes_for_list`, `test_non_list_is_coerced_and_fails_every_check` |
| `scored_runs` | `test_scored_runs_pass_and_fail_details` |
| `enough_repeats` | `test_enough_repeats_respects_min_runs`, `test_non_positive_min_runs_floors_to_zero` |
| `cv_defined` | `test_cv_defined_for_identical_runs`, `test_cv_defined_detail_falls_back_to_reason` |
| `spread_acceptable` | `test_spread_acceptable_within_max_cv`, `test_spread_unacceptable_beyond_max_cv` |
| Check-row sanitation | `test_check_rows_list_none_and_empty_silent`, `test_check_rows_list_warns_on_non_list`, `test_check_rows_list_skips_and_warns_on_malformed_rows`, `test_check_rows_list_rejects_numpy_bool_here`, `test_check_rows_list_warns_when_no_usable_rows` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_stable`, `test_headline_cv_none_renders_na`, `test_headline_nan_cv_renders_nan_percent`, `test_headline_unstable_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_artifacts` |

## Verification strategy

One contract-test group per EARS section; every malformed / empty / **warning** branch called out
in the spec has an asserting test (lessons from the Spec 057/059/061/062 rejections, which faulted
specifically on undefined non-`int`/`float` numeric types, untested warning-emission branches, and
unverified `int`-vs-`bool` rejection — all covered explicitly here).

Expected details and headline strings are pinned as **literal** values rather than rebuilt from the
module's own formatting, so a silent wording change is caught. Warning emission is asserted with
`caplog` on the `benchmark.repeatability_gate` logger for each warn branch.

The **recorded divergence** (this module's `_is_number` has no finiteness/`OverflowError` guard,
unlike every sibling gate) is asserted directly rather than glossed: `NaN`/`inf`/oversized-`int`
are pinned as accepted, and the resulting `cv nan%` headline is pinned as as-built. numpy is not a
test dependency; the numpy-bool **rejection** is exercised with a stand-in whose
`type(...).__name__` is asserted to be `bool_`, proving this module (unlike the newer gates) has no
`_NUMPY_BOOL_TYPENAMES` allowance. Integration and CLI coverage stay in
`tests/test_repeatability_gate.py`.
