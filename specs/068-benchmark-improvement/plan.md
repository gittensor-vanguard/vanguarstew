# Plan 068 — improvement (adoption) gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1900

Maps the [spec](./spec.md) onto `benchmark/improvement.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_068_improvement.py` |
| ------------ | -------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Helpers | `test_is_number_semantics`, `test_is_number_rejects_oversized_int`, `test_num_formats_or_na`, `test_headline_source_generalization_vs_top_level`, `test_artifact_error_top_level_and_per_repo` |
| Gate | `test_result_carries_all_keys`, `test_adopts_on_sufficient_gain`, `test_holds_on_insufficient_gain`, `test_both_scored_reports_baseline_error`, `test_both_scored_reports_candidate_error`, `test_both_scored_reports_missing_score`, `test_gain_none_reports_cannot_compare` |
| Checks-row sanitation | `test_check_rows_list_skips_malformed_rows`, `test_check_rows_list_rejects_non_bool_passed`, `test_check_rows_list_warns_when_all_unusable` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_adopt`, `test_headline_hold_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_inputs` |

## Verification strategy

One contract-test group per EARS section; every error / missing-score / malformed-input / non-list
branch called out in the spec has an asserting test (lessons from the Spec 057 / 059 rejections).
Expectations are pinned as **literal** check names, `passed` booleans and detail strings — e.g. a
candidate `{"composite_mean": 0.65, "error": "boom"}` fixes `both_scored` failing with detail
`candidate error: 'boom'` — rather than re-deriving them from the module, so a silent contract
change is caught here instead of masked. Integration and CLI coverage stay in
`tests/test_improvement.py`.
