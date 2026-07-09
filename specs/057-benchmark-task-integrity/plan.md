# Plan 057 — task integrity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1174

Maps the [spec](./spec.md) onto `benchmark/task_integrity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_057_task_integrity.py` |
| ------------ | ------------------------------------------------ |
| Input coercion | `test_dict_helper_returns_dict_or_empty`, `test_is_nonempty_str_semantics` |
| Integrity gate | `test_well_formed_task_set_passes`, `test_duplicate_freeze_points_fail`, `test_empty_revealed_window_fails`, `test_result_always_includes_required_keys` |
| Fail-closed edge cases | `test_non_list_tasks_fail_closed`, `test_empty_task_list_fails_is_task_list`, `test_missing_freeze_commit_fails_closed`, `test_missing_revealed_key_fails_closed` |
| Failed checks | `test_failed_checks_helper` |
| Task integrity headline | `test_headline_sound_exact`, `test_headline_degenerate_exact`, `test_headline_no_checks_exact` |
| Pure evaluation | `test_check_does_not_mutate_input` |

## Verification strategy

One contract-test group per EARS section; integration and CLI coverage stay in
`tests/test_task_integrity.py`.
