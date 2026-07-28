# Plan 075 — repo-set readiness gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1939

Maps the [spec](./spec.md) onto `benchmark/repo_set_readiness.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_075_repo_set_readiness.py` |
| ------------ | ----------------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Config validation | `test_non_dict_config_reports_literal_type_name`, `test_dict_config_failing_validate_repo_set_short_circuits`, `test_valid_config_passes_and_runs_remaining_checks_in_order` |
| `min_tuned` / `min_held_out` | `test_min_tuned_detail_and_pass_fail`, `test_min_held_out_detail_and_pass_fail`, `test_zero_or_negative_threshold_always_passes`, `test_thresholds_are_configurable_and_echoed` |
| `pre_llm_windows` | `test_missing_freeze_window_key_is_late`, `test_empty_freeze_window_is_late`, `test_freeze_window_without_before_is_late`, `test_before_after_cutoff_is_late`, `test_before_equal_to_cutoff_is_not_late`, `test_late_names_sorted_in_detail` |
| `no_placeholder_sources` | `test_placeholder_source_fails_in_entry_order` |
| Result shape | `test_short_circuit_result_omits_repo_counts`, `test_success_result_carries_repo_counts` |
| `failed_checks` | `test_failed_checks_non_dict_result`, `test_failed_checks_order_follows_checks` |
| `readiness_headline` | `test_headline_invalid_result`, `test_headline_no_checks_evaluated`, `test_headline_ready_uses_question_mark_fallback`, `test_headline_not_ready_lists_every_failed_check` |
| Checks-row sanitation | `test_check_rows_list_none_is_silent_non_list_warns`, `test_check_rows_list_skips_malformed_rows`, `test_check_rows_list_warns_when_all_unusable` |
| Pure evaluation | `test_check_readiness_does_not_mutate_config` |

## Verification strategy

One contract-test group per EARS section, each asserting **literal** check names, `passed` values,
and detail strings pinned by reading the live module — not re-derived from it. This issue drew two
prior closures for incompleteness (PR #1940: the missing/malformed-`freeze_window` arm and the
non-dict `type(config).__name__` derivation were under-specified; no multi-failure-headline or
negative-threshold test existed), so this pass adds those explicitly:

- A type-name matrix (`None`, `list`, `str`, `int`, `float`, `bool`) for the `valid_config` failure
  detail, since `bool` is a common near-miss (`isinstance(True, dict)` is `False`, so a stray `true`
  config value still reports a clean type name rather than being mistaken for an object).
- Three distinct `freeze_window` absence shapes for `pre_llm_windows` — key omitted entirely from
  the raw repo entry (defaults to `{}`), an explicit empty `freeze_window: {}`, and a
  `freeze_window` present with unrelated keys but no `before` — plus the strict `>` boundary
  (`before == PRE_LLM_CUTOFF` passes; one day later fails).
- A deliberate multi-check-failure config (fails `min_tuned`, `pre_llm_windows`, and
  `no_placeholder_sources` at once) asserting the `NOT READY` headline's `f/n` count and
  comma-joined name list cover every failure, not just the first.
- Negative and zero thresholds for `min_tuned`/`min_held_out`, which always pass since a repo count
  is never negative.

## Out of scope

No changes to `repo_set_readiness.py`, `repo_set.py`, or `scripts/repo_set_readiness.py`.
Documentation and tests only.
