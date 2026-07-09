# Plan 057 — task integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1174

Maps the [spec](./spec.md) onto `benchmark/task_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_057_task_integrity.py` |
| ------------ | ----------------------------------------------- |
| Input coercion | `test_dict_helper_returns_dict_or_empty`, `test_is_nonempty_str_semantics` |
| Integrity gate | `test_well_formed_task_set_passes`, `test_duplicate_freeze_points_fail`, `test_empty_revealed_window_fails`, `test_non_list_revealed_window_fails`, `test_result_always_includes_required_keys` |
| Fail-closed cascade for a non-object list (Finding 1) | `test_list_with_non_dict_entries_fails_closed`, `test_mixed_list_with_one_non_dict_entry_fails_closed` |
| `distinct_freeze_points` field semantics (Finding 3) | `test_distinct_freeze_points_field_dedupes_when_duplicates_exist`, `test_distinct_freeze_points_field_independent_of_gate` |
| Fail-closed edge cases | `test_non_list_tasks_fail_closed`, `test_empty_task_list_fails_is_task_list`, `test_missing_freeze_commit_fails_closed`, `test_missing_revealed_key_fails_closed` |
| Failed checks | `test_failed_checks_helper` |
| Task integrity headline | `test_headline_sound_exact`, `test_headline_degenerate_exact`, `test_headline_no_checks_exact` |
| Pure evaluation (Finding 2) | `test_check_does_not_mutate_input_for_every_shape`, `test_check_task_integrity_performs_no_io` |

## Reviewer findings → closure

| Finding (PR #1288, closed) | Spec section | Test(s) |
| -------------------------- | ------------ | ------- |
| 1 — no test for a list with non-`dict` entries (int/str/None) | *Fail-closed cascade for a non-object list* | `test_list_with_non_dict_entries_fails_closed`, `test_mixed_list_with_one_non_dict_entry_fails_closed` |
| 2 — non-mutation test not visible / shallow | *Pure evaluation* | `test_check_does_not_mutate_input_for_every_shape` (deep-copy every shape), `test_check_task_integrity_performs_no_io` |
| 3 — `distinct_freeze_points` ambiguous with duplicates | *`distinct_freeze_points` field semantics* | `test_distinct_freeze_points_field_dedupes_when_duplicates_exist`, `test_distinct_freeze_points_field_independent_of_gate` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_task_integrity.py`.
