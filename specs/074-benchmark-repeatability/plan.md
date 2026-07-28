# Plan 074 — repeatability assessment

- **Status:** draft (SDD Phase 2 — Plan)
- **Spec:** [`spec.md`](./spec.md) · **Issue:** #1922

Maps the [spec](./spec.md) onto `benchmark/repeatability.py` as-built. No product code.

## EARS → test mapping

| Spec section | Test group in `test_spec_074_repeatability.py` |
| ------------ | ---------------------------------------------- |
| Constants | `test_constants_are_pinned` |
| Helpers | `test_round_helper`, `test_coerce_runs`, `test_effective_min_runs`, `test_repeat_not_clean_detail`, `test_repeatability_artifacts_coercion` |
| Assessment | `test_result_carries_all_keys`, `test_stable_set_reports_distribution`, `test_unstable_when_cv_exceeds_max`, `test_not_clean_repeat_returns_early`, `test_no_scored_runs`, `test_insufficient_runs`, `test_zero_mean_nonzero_spread_cv_none`, `test_identical_runs_cv_zero` |
| Headline | `test_headline_no_scored_runs`, `test_headline_inconclusive`, `test_headline_stable`, `test_headline_unstable` |
| Pure evaluation | `test_assess_does_not_mutate_inputs` |

## Verification strategy

One contract-test group per EARS section; every not-clean / no-score / insufficient-runs /
zero-mean / non-list branch called out in the spec has an asserting test (lessons from the Spec 057
/ 059 rejections, and the finding lists on the closed Spec 068 / 069 PRs). Expectations are
**literal**, using score sets chosen so `round(mean, 3)` / `round(stdev, 3)` / `round(cv, 3)` are
exact and stable across platforms — e.g. `[0.60, 0.62, 0.64]` fixes `mean = 0.62`, `stddev = 0.02`,
`cv = 0.032`, and `[0.50, 0.70]` fixes `cv = 0.235` (over the `0.05` bound) — rather than re-deriving
them from the module. The `headline_score` / `check_run_clean` dependencies are exercised through
real artifacts, not mocked. Integration and CLI coverage stay in `tests/test_repeatability.py`.
