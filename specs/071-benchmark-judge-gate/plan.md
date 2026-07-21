# Plan 071 — judge robustness gate

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1914

Maps the [spec](./spec.md) onto `benchmark/judge_gate.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_071_judge_gate.py` |
| ------------ | ------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Numeric / type helpers | `test_is_number_semantics`, `test_is_number_rejects_oversized_int`, `test_is_int_semantics`, `test_dict_helper`, `test_is_passed_accepts_bool_rejects_int`, `test_check_row_field` |
| Dual-order task count | `test_dual_order_tasks_prefers_report_then_stats` |
| Disagreement rate | `test_rate_from_coherent_counts`, `test_rate_derives_dual_from_agree_disagree_tie`, `test_rate_incoherent_pair_falls_back_to_stored`, `test_rate_prefers_order_stats_over_report` |
| Evaluated partition | `test_judge_source_generalization_vs_top_level` |
| Gate | `test_result_carries_all_keys`, `test_robust_run_passes_all`, `test_derived_dual_order_from_task_count`, `test_not_dual_order_fails_closed`, `test_too_few_tasks_fails`, `test_high_disagreement_fails`, `test_non_finite_task_count_fails_closed`, `test_non_dict_result_fails_not_raises` |
| Checks-row sanitation | `test_check_rows_list_skips_malformed_rows`, `test_check_rows_list_rejects_non_bool_passed`, `test_check_rows_list_warns_when_all_unusable` |
| Failed checks and headline | `test_failed_checks_names`, `test_headline_no_checks`, `test_headline_robust`, `test_headline_shaky_lists_failures` |
| Pure evaluation | `test_check_does_not_mutate_result` |

## Verification strategy

One contract-test group per EARS section; every non-finite / missing / incoherent-count /
generalization / non-list branch called out in the spec has an asserting test (lessons from the Spec
057 / 059 rejections, and the finding lists on the closed Spec 068 / 069 PRs — every helper's edge
behavior, including `_disagreement_rate_from_telemetry`'s coherence guard and the `_is_number`
NaN/inf/oversized-int cases the closures called out, is pinned). Expectations are **literal** — e.g.
telemetry `{"dual_order_tasks": 5, "disagree": 1}` fixes `disagreement_rate` at `0.2`, and an
incoherent `{"dual_order_tasks": 4, "disagree": 5}` yields `None` rather than a rate above `1.0` —
using values whose `repr` is stable across platforms, rather than re-deriving them from the module.
Integration and CLI coverage stay in `tests/test_judge_gate.py`.
