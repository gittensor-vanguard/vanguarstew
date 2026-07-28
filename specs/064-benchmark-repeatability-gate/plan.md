# Plan 064 — repeatability gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1879

Maps the [spec](./spec.md) onto `benchmark/repeatability_gate.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_064_repeatability_gate.py` |
| ------------ | ---------------------------------------------------- |
| Constants | `test_constants_and_defaults`, `test_effective_min_runs_floor_and_non_int_arms` |
| Helpers | `test_is_number_accepts_int_float_rejects_bool`, `test_is_number_has_no_finiteness_or_overflow_guard`, `test_is_number_rejects_non_int_float_numerics`, `test_dict_helper` |
| Result shape | `test_result_carries_checks_and_spread_metrics`, `test_check_order_and_row_shape`, `test_passed_is_all_checks` |
| `artifacts_is_list` | `test_artifacts_is_list_passes_for_list`, `test_non_list_is_coerced_fails_every_check_and_warns` |
| `scored_runs` | `test_scored_runs_pass_and_fail_details` |
| `enough_repeats` | `test_enough_repeats_details_including_failure_form`, `test_non_positive_min_runs_floors_to_zero` |
| `cv_defined` | `test_cv_defined_for_identical_runs`, `test_cv_defined_fails_on_zero_mean_nonzero_spread`, `test_cv_defined_detail_falls_back_to_reason` |
| `spread_acceptable` | `test_spread_acceptable_within_max_cv`, `test_spread_unacceptable_pins_reason_detail`, `test_spread_detail_on_not_clean_repeat` |
| Check-row sanitation | `test_check_rows_list_none_and_empty_silent`, `test_check_rows_list_warns_on_non_list`, `test_check_rows_list_skips_and_warns_on_malformed_rows`, `test_check_rows_list_accepts_empty_name_here`, `test_check_rows_list_rejects_numpy_bool_here`, `test_check_rows_list_warns_when_no_usable_rows` |
| Failed checks and headline | `test_failed_checks_names_and_non_dict`, `test_headline_no_checks`, `test_headline_stable_literal`, `test_headline_cv_none_renders_na`, `test_headline_nan_cv_renders_nan_percent`, `test_headline_inf_cv_renders_inf_percent`, `test_headline_neg_inf_cv_renders_neg_inf_percent`, `test_headline_oversized_int_cv_raises_overflow`, `test_headline_missing_runs_renders_none`, `test_headline_unstable_counts_sanitized_rows_only` |
| Pure evaluation | `test_check_does_not_mutate_artifacts` |

## Verification strategy

One contract-test group per EARS section; every malformed / empty / **warning** / non-finite
branch called out in the spec has an asserting test. This directly addresses the closure findings
on the prior Spec 064 attempt — the `inf` / `-inf` headline renderings and the oversized-int
`OverflowError` are **pinned by tests** here, not just recorded in prose, and the spec now
*justifies* each divergence (presentation-only guard, non-finite values unreachable through the
composed `headline_score` → `assess_repeatability` pipeline) instead of merely noting it — as
well as the Spec 057/059/061/062 rejection class (undefined non-`int`/`float` numeric types,
untested warning-emission branches, unverified `int`-vs-`bool` rejection).

Expected details and headline strings are pinned as **literal** values rather than rebuilt from
the module's own formatting, so a silent wording change is caught; every pinned value has a
platform-stable `repr`. Warning emission is asserted with `caplog` on the
`benchmark.repeatability_gate` logger (and `benchmark.repeatability` for the non-list coercion)
for each warn branch. numpy is not a test dependency: the numpy-bool **rejection** is exercised
with a stand-in whose `type(...).__name__` is asserted to be `bool_`, proving this module (unlike
`run_clean`'s `_is_passed` allowance) admits only native `bool` verdicts. Integration and CLI
coverage stay in `tests/test_repeatability_gate.py`.
