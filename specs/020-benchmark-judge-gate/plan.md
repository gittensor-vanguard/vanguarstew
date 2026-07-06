# Plan 020 — pairwise-judge robustness gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #820

Maps the [spec](./spec.md) onto `benchmark/judge_gate.py` as-built. No new product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_020_judge_gate.py` |
| ------------ | ------------------------------------------- |
| Judge robustness checks | `test_check_judge_*` |
| Dual-order task count resolution | `test_dual_order_tasks_*` |
| Disagreement rate handling | `test_disagreement_*`, `test_legitimate_zero_*` |
| Threshold configuration | `test_thresholds_*` |
| Malformed gate-result robustness | `test_check_rows_list_*`, `test_failed_checks_*` |
| Judge headline | `test_judge_headline_*` |
| Pure evaluation | `test_check_judge_does_not_mutate_result` |
