# Plan 050 — margin outlook summary

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1152

Maps the [spec](./spec.md) onto `benchmark/margin_outlook.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_050_margin_outlook.py` |
| ------------ | ----------------------------------------------- |
| Input coercion | `test_non_dict_artifact_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Tally margin | `test_margin_from_tally_happy_path`, `test_margin_from_tally_malformed` |
| Margin resolution | `test_margin_prefers_decisive_margin`, `test_margin_falls_back_to_tally`, `test_margin_falls_back_to_judge_report` |
| Outlook | `test_outlook_ahead_behind_tied`, `test_outlook_none_for_invalid_margin` |
| Margin outlook summary | `test_summarize_happy_path`, `test_missing_data_none_outlook`, `test_summary_always_includes_required_keys` |
| Margin outlook headline | `test_headline_exact_format`, `test_headline_unavailable_exact`, `test_headline_non_dict_summary_coerced` |
| Pure evaluation | `test_summarize_does_not_mutate_artifact` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_margin_outlook.py`.
