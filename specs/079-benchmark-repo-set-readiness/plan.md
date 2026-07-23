# Spec 079 — Plan

## Approach

`benchmark/repo_set_readiness.py` already ships and drives `scripts/repo_set_readiness.py`. This
spec is a **characterization** effort: document the existing readiness contract requested by issue
#1939 and pin it with tests, adding no behaviour. Every asserted value in
`tests/test_spec_079_repo_set_readiness.py` was taken from the live module, not hand-derived.

## Traceability

| AC | Behaviour | Tests |
| --- | --- | --- |
| AC-1 | ready path: check set, order, counts | `test_a_ready_set_passes_and_reports_all_five_checks_in_order`, `test_module_defaults_and_cutoff_are_pinned` |
| AC-2 | invalid / non-dict config short-circuits | `test_an_invalid_config_reports_only_valid_config`, `test_a_non_dict_config_fails_valid_config_without_raising` |
| AC-3 | min_tuned | `test_too_few_tuned_repos_fails_only_min_tuned` |
| AC-4 | min_held_out | `test_too_few_held_out_repos_fails_only_min_held_out` |
| AC-5 | pre_llm_windows (late + unbounded) | `test_a_late_freeze_window_fails_pre_llm_windows`, `test_an_unbounded_freeze_window_fails_pre_llm_windows` |
| AC-6 | no_placeholder_sources | `test_a_starter_placeholder_source_fails_no_placeholder_sources` |
| AC-7 | configurable thresholds | `test_thresholds_are_configurable` |
| AC-8 | headline strings | `test_ready_headline_names_the_tuned_and_held_out_counts`, `test_invalid_config_headline_counts_the_single_failing_check`, `test_readiness_headline_on_malformed_results` |
| AC-9 | malformed-result tolerance + row sanitizer | `test_failed_checks_on_a_non_dict_result_returns_a_sentinel`, `test_failed_checks_tolerates_a_non_list_checks_container`, `test_check_rows_list_returns_empty_for_none_and_empty`, `test_check_rows_list_warns_and_empties_a_tuple`, `test_check_rows_list_skips_a_non_dict_row`, `test_check_rows_list_skips_a_row_missing_required_keys`, `test_check_rows_list_skips_a_blank_name`, `test_check_rows_list_skips_a_non_bool_passed` |

## Dependency note

`check_readiness` composes `benchmark.repo_set.validate_repo_set` (well-formedness → the single
`valid_config` check) and `is_placeholder_source` (the placeholder check). Those contracts are
stated in the spec and pinned at their boundary by the invalid-config and placeholder tests, so
the gate's behaviour is fully defined here rather than resting on an implicit helper. The
validator and placeholder-URL set are owned by `benchmark/repo_set.py` and are out of scope for
change.

## Risks

- **Cutoff is a string comparison.** `pre_llm_windows` compares `freeze_window.before` to
  `PRE_LLM_CUTOFF` lexicographically; the tests fix that an absent/late `before` fails and a
  pre-cutoff ISO date passes, so the comparison semantics are pinned, not just the happy path.
- **`_check_rows_list` is the shared sanitizer** behind both `failed_checks` and
  `readiness_headline`; each rejection reason (non-list, non-dict row, missing key, blank name,
  non-bool `passed`) has its own test so a partial regression is pinpointable.

## Out of scope

No changes to `repo_set_readiness.py`, `repo_set.py`, or the scoring modules. Documentation and
tests only.
