# Plan 035 — win rate summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #972

Maps the [spec](./spec.md) onto `benchmark/win_rate.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_035_win_rate.py` |
| ------------ | ------------------------------------------------ |
| Input coercion | `test_non_dict_result_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Tally counts | `test_tally_counts_happy_path`, `test_tally_counts_missing_tally`, `test_tally_counts_non_dict_tally`, `test_tally_counts_negative_rejected`, `test_tally_counts_non_integer_rejected`, `test_tally_counts_missing_keys_treated_as_none` |
| Win rate summary | `test_rates_from_complete_tally`, `test_zero_total_yields_zero_counts_none_rates`, `test_missing_tally_all_none`, `test_malformed_tally_all_none`, `test_summary_always_includes_required_keys`, `test_zero_total_distinct_from_missing_tally` |
| Win rate headline | `test_headline_happy_path_exact_format`, `test_headline_two_thirds_exact_format`, `test_headline_zero_total_exact_format`, `test_headline_missing_tally_exact_format`, `test_headline_nan_rate_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_win_rate.py`.
