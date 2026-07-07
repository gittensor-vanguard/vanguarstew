# Plan 046 — win rate summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1124

Maps the [spec](./spec.md) onto `benchmark/win_rate.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_046_win_rate.py` |
| ------------ | ----------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Tally parsing | `test_tally_counts_happy_path`, `test_tally_counts_missing_or_malformed` |
| Win rate summary | `test_summarize_happy_path`, `test_zero_total_none_rates`, `test_malformed_tally_all_none`, `test_summary_always_includes_required_keys` |
| Win rate headline | `test_headline_happy_path_exact_format`, `test_headline_zero_total_exact`, `test_headline_missing_total`, `test_headline_nan_rate_shows_na`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_win_rate.py`.
