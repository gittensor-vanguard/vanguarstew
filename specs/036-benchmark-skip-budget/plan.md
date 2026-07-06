# Plan 036 — skip budget gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #989

Maps the [spec](./spec.md) onto `benchmark/skip_budget.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_036_skip_budget.py` |
| ------------ | ---------------------------------------------- |
| Constants | `test_default_min_scored_and_max_skip_rate` |
| Whole-number count semantics | `test_is_int_rejects_bool`, `test_is_int_rejects_float_whole_numbers`, `test_is_int_rejects_numpy_integer_scalars` |
| Input coercion | `test_non_dict_result_coerced`, `test_dict_helper_returns_dict_or_empty`, `test_extra_input_keys_ignored` |
| Multi-repo accounting | `test_counts_happy_path`, `test_counts_missing_skipped_ok`, `test_counts_zero_repos`, `test_counts_negative_scored`, `test_counts_scored_exceeds_repos`, `test_counts_inconsistent_skipped`, `test_counts_non_integer_counts` |
| Skip rate | `test_skip_rate_computed_and_rounded`, `test_skip_rate_none_when_incoherent`, `test_full_coverage_skip_rate_is_zero_point_zero` |
| Gate checks | `test_gate_always_reports_three_checks`, `test_well_covered_run_passes`, `test_too_few_scored_fails`, `test_skip_rate_bound_inclusive`, `test_single_repo_fails_accounting` |
| Gate result shape | `test_gate_returns_required_keys`, `test_incoherent_accounting_yields_none_fields` |
| Malformed gate-result robustness | `test_check_rows_list_*`, `test_failed_checks_tolerates_malformed_result` |
| Skip budget headline | `test_headline_covered_exact_format`, `test_headline_under_covered_exact_format`, `test_headline_no_checks_evaluated`, `test_headline_never_bare_none_from_gate`, `test_headline_extra_result_keys_ignored` |
| Pure evaluation | `test_check_skip_budget_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_skip_budget.py`.
