# Plan 036 — skip budget gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #989

Maps the [spec](./spec.md) onto `benchmark/skip_budget.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_036_skip_budget.py` |
| ------------ | ---------------------------------------------- |
| Input coercion | `test_non_dict_result_coerced_to_empty_dict`, `test_dict_helper_returns_dict_or_empty` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers` |
| Boolean semantics | `test_is_bool_accepts_bool_rejects_int` |
| Multi-repo accounting | `test_counts_coherent_tally`, `test_counts_incoherent_returns_none`, `test_counts_skipped_field_must_reconcile` |
| Gate evaluation | `test_well_covered_run_passes`, `test_too_few_scored_fails_enough_scored`, `test_too_many_skipped_fails_skip_within_budget`, `test_incoherent_tally_fails_dependent_checks_closed`, `test_bounds_are_inclusive`, `test_default_thresholds`, `test_result_always_includes_required_keys` |
| Checks-row sanitization | `test_check_rows_list_none_and_empty_are_silent`, `test_check_rows_list_non_list_warns_and_empties`, `test_check_rows_list_skips_unusable_rows`, `test_check_rows_list_all_unusable_warns` |
| Failed checks | `test_failed_checks_names_failed_rows`, `test_failed_checks_robust_to_malformed_checks` |
| Skip budget headline | `test_headline_covered_exact_format`, `test_headline_under_covered_exact_format`, `test_headline_no_checks_evaluated`, `test_headline_non_list_checks_shows_no_checks` |
| Pure evaluation | `test_check_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_skip_budget.py`.
