# Plan 056 — task uniformity gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1171

Maps the [spec](./spec.md) onto `benchmark/task_uniformity.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_056_task_uniformity.py` |
| ------------ | ------------------------------------------------ |
| Input coercion | `test_window_len_semantics`, `test_dict_helper_returns_dict_or_empty` |
| Uniformity gate | `test_uniform_windows_pass`, `test_uneven_windows_fail`, `test_missing_revealed_window_fails`, `test_malformed_tasks_fail_gracefully`, `test_result_always_includes_required_keys` |
| Failed checks | `test_failed_checks_helper` |
| Task uniformity headline | `test_headline_uniform_exact`, `test_headline_uneven_exact`, `test_headline_no_checks_exact` |
| Pure evaluation | `test_check_does_not_mutate_input` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_task_uniformity.py`.
