# Plan 055 — task independence gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1168

Maps the [spec](./spec.md) onto `benchmark/task_independence.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_055_task_independence.py` |
| ------------ | -------------------------------------------------- |
| Constants | `test_default_horizon_constant` |
| Input coercion | `test_is_nonneg_int_semantics`, `test_dict_helper_returns_dict_or_empty` |
| Independence gate | `test_independent_tasks_pass`, `test_overlapping_windows_fail`, `test_single_task_trivially_independent`, `test_malformed_tasks_fail_gracefully`, `test_result_always_includes_required_keys` |
| Failed checks | `test_failed_checks_helper` |
| Task independence headline | `test_headline_independent_exact`, `test_headline_overlapping_exact`, `test_headline_no_checks_exact` |
| Pure evaluation | `test_check_does_not_mutate_input` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_task_independence.py`.
