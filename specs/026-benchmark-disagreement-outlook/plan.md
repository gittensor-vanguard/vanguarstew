# Plan 026 — disagreement outlook

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #874

Maps the [spec](./spec.md) onto `benchmark/disagreement_outlook.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_026_disagreement_outlook.py` |
| ------------ | ----------------------------------------------------- |
| Input guard | `test_non_dict_artifact_*` |
| Telemetry source | `test_reads_judge_report_*`, `test_falls_back_to_judge_order_stats` |
| `dual_order_tasks` | `test_dual_order_tasks_*` |
| `disagreement_rate` | `test_disagreement_rate_*`, `test_nan_and_inf_rate_*` |
| Verdict | `test_verdict_stable_*`, `test_verdict_unstable_*`, `test_verdict_none_*` |
| Threshold parameter | `test_default_threshold_*`, `test_non_finite_threshold_*` |
| Artifact kind | `test_kind_from_artifact_kind` |
| Headline | `test_headline_*` |
| Pure evaluation | `test_does_not_mutate_artifact`, `test_no_io_imports` |

## Verification strategy

One contract-test group per EARS section; integration and CLI tests stay in
`tests/test_disagreement_outlook.py`.
