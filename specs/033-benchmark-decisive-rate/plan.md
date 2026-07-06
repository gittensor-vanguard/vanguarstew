# Plan 033 — decisive rate summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #949

Maps the [spec](./spec.md) onto `benchmark/decisive_rate.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_033_decisive_rate.py` |
| ------------ | ---------------------------------------------- |
| Input coercion | `test_non_dict_result_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Tally parsing | `test_tally_not_dict_returns_none`, `test_malformed_counts_rejected`, `test_valid_tally_counts_tuple` |
| Summarize — malformed tally | `test_missing_tally_yields_all_none` |
| Summarize — zero total | `test_zero_total_yields_none_rates` |
| Summarize — positive total | `test_decisive_and_tie_shares_from_complete_tally` |
| Summarize — all ties (`0.0` vs missing) | `test_all_ties_yields_zero_decisive_rate` |
| Finite numeric semantics | `test_bool_and_non_finite_not_numeric` |
| Headline — no tally | `test_headline_no_tally_when_zero_or_invalid_total` |
| Headline — happy path | `test_headline_happy_path` |
| Headline — non-finite rates | `test_headline_nan_rate_shows_na` |
| Logging | `test_module_emits_no_logs` |
| Pure evaluation | `test_summarize_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_decisive_rate.py`.
